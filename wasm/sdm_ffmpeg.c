/*
 * sdm_ffmpeg: the one ffmpeg invocation `sdm quality` makes, for the browser build.
 *
 *   ffmpeg -nostdin -hide_banner -nostats -v verbose -i PATH -map 0:a:0
 *          -af FILTERGRAPH -f f32le -
 *
 * Why not the ffmpeg program itself: since FFmpeg 6.0 it needs threads
 * (configure: ffmpeg_deps="... threads"), and the browser build runs each
 * tool as a fresh, synchronous, single-threaded WebAssembly instance (see
 * frontend/src/browser/tools.ts). FFmpeg 5.1, the last single-threaded
 * release, does not print the decode-error count `quality` reports, and its
 * decoders and resampler differ from the 7.1.1 `quality` was measured with.
 * So this links the same 7.1.1 libraries and does what the 7.1.1 program does
 * for that one command line, mirroring fftools/ffmpeg_dec.c and
 * fftools/ffmpeg_demux.c where it matters to what `measure.py` reads:
 *
 *   - the first audio stream (-map 0:a:0), every other stream discarded;
 *   - decoder options as the CLI sets them (threads=auto, pkt_timebase);
 *   - errors counted as the CLI counts them: a packet the decoder refuses, a
 *     frame it fails to produce; decoding carries on after either;
 *   - the filtergraph as the CLI builds it: abuffer from the first frame, the
 *     -af chain, aformat to the encoder's sample format, abuffersink;
 *   - stdout: the samples as interleaved little-endian float32, as the f32le
 *     muxer writes them;
 *   - stderr: the library's own log at the requested level (so ebur128's
 *     Summary is the filter's own text), and the closing "Input stream #0:N
 *     (audio): N packets read (N bytes); N frames decoded; N decode errors"
 *     line in fftools' exact format, which `measure.py` parses.
 *
 * Any other option is refused: this is not a general ffmpeg, and silently
 * ignoring a flag would make a result look measured that was not.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <inttypes.h>

#include <libavcodec/avcodec.h>
#include <libavfilter/avfilter.h>
#include <libavfilter/buffersink.h>
#include <libavfilter/buffersrc.h>
#include <libavformat/avformat.h>
#include <libavutil/channel_layout.h>
#include <libavutil/opt.h>

typedef struct {
    const char *input;
    const char *filters;   /* -af, or NULL */
    const char *format;    /* -f: f32le only */
    const char *output;    /* "-" or "pipe:1" */
} Options;

typedef struct {
    AVFormatContext *fmt;
    AVCodecContext *dec;
    AVFilterGraph *graph;
    AVFilterContext *src, *sink;
    int stream;
    uint64_t packets, bytes, frames, samples, errors;
} State;

static int fail(const char *message)
{
    av_log(NULL, AV_LOG_FATAL, "%s\n", message);
    return 1;
}

static int set_level(const char *name)
{
    static const struct { const char *name; int level; } levels[] = {
        { "quiet", AV_LOG_QUIET }, { "panic", AV_LOG_PANIC }, { "fatal", AV_LOG_FATAL },
        { "error", AV_LOG_ERROR }, { "warning", AV_LOG_WARNING }, { "info", AV_LOG_INFO },
        { "verbose", AV_LOG_VERBOSE }, { "debug", AV_LOG_DEBUG }, { "trace", AV_LOG_TRACE },
    };
    for (size_t i = 0; i < sizeof(levels) / sizeof(levels[0]); i++) {
        if (!strcmp(name, levels[i].name)) {
            av_log_set_level(levels[i].level);
            return 0;
        }
    }
    return -1;
}

static int parse(int argc, char **argv, Options *o)
{
    memset(o, 0, sizeof(*o));
    for (int i = 1; i < argc; i++) {
        const char *a = argv[i];
        const char *next = i + 1 < argc ? argv[i + 1] : NULL;
        if (!strcmp(a, "-nostdin") || !strcmp(a, "-hide_banner") || !strcmp(a, "-nostats") || !strcmp(a, "-y")) {
            continue;
        } else if ((!strcmp(a, "-v") || !strcmp(a, "-loglevel")) && next) {
            if (set_level(next) < 0)
                return fail("sdm_ffmpeg: unknown log level");
            i++;
        } else if (!strcmp(a, "-i") && next && !o->input) {
            o->input = argv[++i];
        } else if (!strcmp(a, "-map") && next) {
            if (strcmp(next, "0:a:0"))
                return fail("sdm_ffmpeg: only -map 0:a:0 is supported");
            i++;
        } else if (!strcmp(a, "-af") && next) {
            o->filters = argv[++i];
        } else if (!strcmp(a, "-f") && next) {
            o->format = argv[++i];
        } else if (i == argc - 1 && (!strcmp(a, "-") || a[0] != '-')) {
            o->output = a;
        } else {
            av_log(NULL, AV_LOG_FATAL, "sdm_ffmpeg: unsupported option '%s'\n", a);
            return 1;
        }
    }
    if (!o->input || !o->output)
        return fail("sdm_ffmpeg: usage: -i INPUT [-map 0:a:0] [-af FILTERS] -f f32le -");
    if (!o->format || strcmp(o->format, "f32le"))
        return fail("sdm_ffmpeg: only -f f32le is supported");
    if (strcmp(o->output, "-") && strcmp(o->output, "pipe:1") && strcmp(o->output, "pipe:"))
        return fail("sdm_ffmpeg: only standard output (-) is supported");
    return 0;
}

static int open_input(State *s, const char *path)
{
    int ret = avformat_open_input(&s->fmt, path, NULL, NULL);
    if (ret < 0) {
        av_log(NULL, AV_LOG_ERROR, "Error opening input: %s\n", av_err2str(ret));
        av_log(NULL, AV_LOG_ERROR, "Error opening input file %s.\n", path);
        av_log(NULL, AV_LOG_ERROR, "Error opening input files: %s\n", av_err2str(ret));
        return ret;
    }
    ret = avformat_find_stream_info(s->fmt, NULL);
    if (ret < 0) {
        av_log(NULL, AV_LOG_FATAL, "%s: could not find codec parameters\n", path);
        return ret;
    }
    av_dump_format(s->fmt, 0, path, 0);

    s->stream = -1;
    for (unsigned i = 0; i < s->fmt->nb_streams; i++) {
        AVStream *st = s->fmt->streams[i];
        if (s->stream < 0 && st->codecpar->codec_type == AVMEDIA_TYPE_AUDIO)
            s->stream = (int)i;
        else
            st->discard = AVDISCARD_ALL;  /* as the CLI does for unmapped streams */
    }
    if (s->stream < 0) {
        av_log(NULL, AV_LOG_FATAL, "Stream map '0:a:0' matches no streams.\n");
        return AVERROR_STREAM_NOT_FOUND;
    }

    AVStream *st = s->fmt->streams[s->stream];
    /* fftools' guess_input_channel_layout: a layout that is only a channel
     * count ("2 channels", as WAVs without a channel mask have) becomes the
     * default layout for that count, or no filter could pick one. */
    if (st->codecpar->ch_layout.order == AV_CHANNEL_ORDER_UNSPEC) {
        char name[256];
        int channels = st->codecpar->ch_layout.nb_channels;
        av_channel_layout_uninit(&st->codecpar->ch_layout);
        av_channel_layout_default(&st->codecpar->ch_layout, channels);
        if (st->codecpar->ch_layout.order != AV_CHANNEL_ORDER_UNSPEC) {
            av_channel_layout_describe(&st->codecpar->ch_layout, name, sizeof(name));
            av_log(NULL, AV_LOG_WARNING, "Guessed Channel Layout: %s\n", name);
        }
    }
    const AVCodec *codec = avcodec_find_decoder(st->codecpar->codec_id);
    if (!codec) {
        av_log(NULL, AV_LOG_FATAL, "Decoding requested, but no decoder found for: %s\n",
               avcodec_get_name(st->codecpar->codec_id));
        return AVERROR_DECODER_NOT_FOUND;
    }
    s->dec = avcodec_alloc_context3(codec);
    if (!s->dec)
        return AVERROR(ENOMEM);
    ret = avcodec_parameters_to_context(s->dec, st->codecpar);
    if (ret < 0)
        return ret;
    s->dec->pkt_timebase = st->time_base;
    s->dec->flags |= AV_CODEC_FLAG_COPY_OPAQUE;
    AVDictionary *opts = NULL;
    av_dict_set(&opts, "threads", "auto", 0);
    ret = avcodec_open2(s->dec, codec, &opts);
    av_dict_free(&opts);
    if (ret < 0) {
        av_log(NULL, AV_LOG_ERROR, "Error while opening decoder for input stream #0:%d : %s\n",
               s->stream, av_err2str(ret));
        return ret;
    }
    return 0;
}

/* The graph, from the first decoded frame, as the CLI configures it. */
static int open_graph(State *s, const AVFrame *frame, const char *filters)
{
    char layout[256], args[512];
    int ret;

    s->graph = avfilter_graph_alloc();
    if (!s->graph)
        return AVERROR(ENOMEM);
    s->graph->nb_threads = 1;

    av_channel_layout_describe(&frame->ch_layout, layout, sizeof(layout));
    snprintf(args, sizeof(args), "time_base=1/%d:sample_rate=%d:sample_fmt=%s:channel_layout=%s",
             frame->sample_rate, frame->sample_rate,
             av_get_sample_fmt_name(frame->format), layout);
    ret = avfilter_graph_create_filter(&s->src, avfilter_get_by_name("abuffer"), "graph_0_in_0_0", args, NULL, s->graph);
    if (ret < 0)
        return ret;
    ret = avfilter_graph_create_filter(&s->sink, avfilter_get_by_name("abuffersink"), "out_0_0", NULL, NULL, s->graph);
    if (ret < 0)
        return ret;

    AVFilterContext *format;
    ret = avfilter_graph_create_filter(&format, avfilter_get_by_name("aformat"), "format_out_0_0",
                                       "sample_fmts=flt", NULL, s->graph);
    if (ret < 0)
        return ret;
    ret = avfilter_link(format, 0, s->sink, 0);
    if (ret < 0)
        return ret;

    if (filters && *filters) {
        AVFilterInOut *in = avfilter_inout_alloc(), *out = avfilter_inout_alloc();
        out->name = av_strdup("in");
        out->filter_ctx = s->src;
        out->pad_idx = 0;
        in->name = av_strdup("out");
        in->filter_ctx = format;
        in->pad_idx = 0;
        ret = avfilter_graph_parse_ptr(s->graph, filters, &in, &out, NULL);
        avfilter_inout_free(&in);
        avfilter_inout_free(&out);
        if (ret < 0)
            return ret;
    } else {
        ret = avfilter_link(s->src, 0, format, 0);
        if (ret < 0)
            return ret;
    }
    return avfilter_graph_config(s->graph, NULL);
}

static int drain_sink(State *s, AVFrame *out)
{
    for (;;) {
        int ret = av_buffersink_get_frame(s->sink, out);
        if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF)
            return 0;
        if (ret < 0)
            return ret;
        size_t bytes = (size_t)out->nb_samples * out->ch_layout.nb_channels * sizeof(float);
        if (fwrite(out->data[0], 1, bytes, stdout) != bytes) {
            av_frame_unref(out);
            return AVERROR(EIO);
        }
        av_frame_unref(out);
    }
}

static int filter_frame(State *s, AVFrame *frame, const char *filters, AVFrame *out)
{
    int ret;
    if (!s->graph && (ret = open_graph(s, frame, filters)) < 0) {
        av_log(NULL, AV_LOG_ERROR, "Error configuring filters: %s\n", av_err2str(ret));
        return ret;
    }
    ret = av_buffersrc_add_frame_flags(s->src, frame, AV_BUFFERSRC_FLAG_PUSH);
    if (ret < 0)
        return ret;
    return drain_sink(s, out);
}

/* fftools' packet_decode: send, then take every frame; a refusal or a failure is counted, not fatal. */
static int decode(State *s, AVPacket *pkt, AVFrame *frame, const char *filters, AVFrame *out)
{
    if (pkt && pkt->size == 0)
        return 0;
    int ret = avcodec_send_packet(s->dec, pkt);
    if (ret < 0 && !(ret == AVERROR_EOF && !pkt)) {
        av_log(NULL, AV_LOG_ERROR, "Error submitting %s to decoder: %s\n", pkt ? "packet" : "EOF", av_err2str(ret));
        if (ret != AVERROR_EOF)
            s->errors++;
        return 0;
    }
    for (;;) {
        av_frame_unref(frame);
        ret = avcodec_receive_frame(s->dec, frame);
        if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF)
            return 0;
        if (ret < 0) {
            av_log(NULL, AV_LOG_ERROR, "Decoding error: %s\n", av_err2str(ret));
            s->errors++;
            continue;
        }
        if (frame->decode_error_flags || (frame->flags & AV_FRAME_FLAG_CORRUPT))
            av_log(NULL, AV_LOG_WARNING, "corrupt decoded frame\n");
        s->frames++;
        s->samples += frame->nb_samples;
        ret = filter_frame(s, frame, filters, out);
        if (ret < 0)
            return ret;
    }
}

int main(int argc, char **argv)
{
    Options o;
    State s = { 0 };
    AVPacket *pkt = av_packet_alloc();
    AVFrame *frame = av_frame_alloc(), *out = av_frame_alloc();
    int ret = parse(argc, argv, &o);
    if (ret)
        return ret;

    ret = open_input(&s, o.input);
    if (ret < 0)
        goto end;

    while ((ret = av_read_frame(s.fmt, pkt)) >= 0) {
        if (pkt->stream_index == s.stream) {
            s.packets++;
            s.bytes += pkt->size;
            ret = decode(&s, pkt, frame, o.filters, out);
        }
        av_packet_unref(pkt);
        if (ret < 0)
            goto end;
    }
    if (ret != AVERROR_EOF)
        av_log(NULL, AV_LOG_ERROR, "Error during demuxing: %s\n", av_err2str(ret));
    ret = decode(&s, NULL, frame, o.filters, out);
    if (ret >= 0 && s.graph) {
        ret = av_buffersrc_add_frame_flags(s.src, NULL, 0);
        if (ret >= 0)
            ret = drain_sink(&s, out);
    }
    fflush(stdout);

    av_log(NULL, AV_LOG_VERBOSE, "Input file #0 (%s):\n", o.input);
    av_log(NULL, AV_LOG_VERBOSE,
           "  Input stream #0:%d (audio): %" PRIu64 " packets read (%" PRIu64 " bytes); "
           "%" PRIu64 " frames decoded; %" PRIu64 " decode errors (%" PRIu64 " samples); \n",
           s.stream, s.packets, s.bytes, s.frames, s.errors, s.samples);
    av_log(NULL, AV_LOG_VERBOSE, "  Total: %" PRIu64 " packets (%" PRIu64 " bytes) demuxed\n", s.packets, s.bytes);

end:
    avfilter_graph_free(&s.graph);  /* ebur128 prints its Summary here, as in the CLI */
    avcodec_free_context(&s.dec);
    avformat_close_input(&s.fmt);
    av_packet_free(&pkt);
    av_frame_free(&frame);
    av_frame_free(&out);
    return ret < 0 && ret != AVERROR_EOF ? 1 : 0;
}
