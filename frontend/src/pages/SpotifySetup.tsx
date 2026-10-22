// The one-time Spotify setup, for both front ends: the app to create on
// Spotify's side so `playlist-diff` (given a link) and `playlist-export` can log
// in. Linked from the browser build's login box and from `sdm web`'s
// --client-id field. Where the two differ — the redirect address, where the
// client ID goes, how long a login lasts — the page asks `browser`.
//
// Spotify moves these rules (its February 2026 changes rewrote them), so the
// page says when they were checked.
import { useEffect, type ReactNode } from "react";
import { browser, type Session } from "../api";
import { CopyButton } from "../components";
import { href } from "../router";

/** Each front end's redirect address, for one app used from both. The CLI's is core/spotify.py's default. */
const SITE_REDIRECT_URI = "https://sdm.eigenomar.com/";
const CLI_REDIRECT_URI = "http://127.0.0.1:8765/callback";

const SETX = 'setx SDM_SPOTIFY_CLIENT_ID "<client id>"';

function External({ to, children }: { to: string; children: ReactNode }) {
  return (
    <a href={to} target="_blank" rel="noreferrer">
      {children}
    </a>
  );
}

function CopyLine({ text }: { text: string }) {
  return (
    <div className="copy-line">
      <code>{text}</code>
      <CopyButton text={text} />
    </div>
  );
}

const command = (name: string) => (
  <a href={href(`/run/${name}`)}>
    <code>{name}</code>
  </a>
);

export function SpotifySetup({ session, section }: { session: Session; section: string | null }) {
  // ?section= in place of a #fragment, which the router owns.
  useEffect(() => {
    if (section) document.getElementById(section)?.scrollIntoView();
  }, [section]);

  const redirect = session.spotify_redirect_uri;
  const onLocalhost = browser !== null && window.location.hostname === "localhost";
  // What "exactly" means for this address: the site's, or a loopback one (sdm web, a local test of the site).
  const path = new URL(redirect).pathname;
  const exactly = redirect.startsWith("https:")
    ? "https, no www, and the slash at the end."
    : `http, the IP address 127.0.0.1 (Spotify refuses localhost), the port, and ${path === "/" ? "the slash at the end" : path}.`;

  return (
    <div className="page guide">
      <header className="page-head">
        <h1>Spotify setup</h1>
        <p>
          A playlist link, in {command("playlist-diff")} or {command("playlist-export")}, is read through Spotify&apos;s
          Web API, logged in as you. For that Spotify wants a <strong>client ID</strong>: the ID of an app registered on
          its developer site. You make your own, once. It is free and takes about five minutes.
        </p>
        <p className="muted">
          Why not one app built into sdm? Spotify keeps every new app in <em>development mode</em>, which allows five
          users, and grants more only to registered businesses with 250,000 monthly users. One shared app would work for
          five people.
        </p>
      </header>

      <section id="before">
        <h2>Before you start</h2>
        <ul>
          <li>
            <strong>Spotify Premium</strong> on the account that creates the app. Since February 2026 Spotify requires
            it of every development-mode app&apos;s owner; if the subscription lapses, the app stops working until it is
            renewed.
          </li>
          <li>
            Nothing else: no client secret, no payment details, no server. The login runs between your browser and
            Spotify.
          </li>
        </ul>
      </section>

      <section id="create">
        <h2>1. Create the app</h2>
        <ol className="steps">
          <li>
            Open the <External to="https://developer.spotify.com/dashboard">Spotify developer dashboard</External> and
            log in with your Spotify account. The first time, it asks you to accept the Developer Terms and may ask you
            to confirm your email address.
          </li>
          <li>
            Click <strong>Create app</strong>.
          </li>
          <li>
            <strong>App name</strong> and <strong>App description</strong>: anything. &quot;sdm&quot; and &quot;Compare
            my playlists with my music&quot; will do; Spotify shows both on the page where you approve the login. Leave{" "}
            <strong>Website</strong> empty.
          </li>
          <li>
            <strong>Redirect URIs</strong>: enter this address and click <strong>Add</strong>.
            <CopyLine text={redirect} />
            It must match character for character — {exactly} It is where Spotify sends you back after you log in, and Spotify sends nowhere it has not been told.
            {onLocalhost && (
              <p className="help warn">
                This page is open at <code>localhost</code>, which Spotify refuses. Open it at{" "}
                <code>127.0.0.1</code> instead, and register that address.
              </p>
            )}
            <p className="help">
              Using sdm in both places? One app can have several redirect URIs: add{" "}
              <code>{browser ? CLI_REDIRECT_URI : SITE_REDIRECT_URI}</code> as well (
              {browser ? <>for sdm on your own machine and <code>sdm web</code></> : "for the browser version"}), and
              use the same client ID in both.
            </p>
          </li>
          <li>
            If the form asks <strong>Which API/SDKs are you planning to use?</strong>, tick <strong>Web API</strong>.
          </li>
          <li>
            Tick the box accepting Spotify&apos;s Developer Terms of Service, and click <strong>Save</strong>.
          </li>
        </ol>
      </section>

      <section id="client-id">
        <h2>2. Copy the client ID</h2>
        <ol className="steps">
          <li>
            On the dashboard, open the app and go to <strong>Settings</strong>.
          </li>
          <li>
            Under <strong>Basic Information</strong>, copy the <strong>Client ID</strong>: 32 characters, digits and the
            letters a–f.
          </li>
          <li>
            Leave the <strong>client secret</strong> alone. sdm never needs it, nothing here asks for it, and it is the
            one value on that page to keep to yourself.
          </li>
        </ol>
      </section>

      <section id="use">
        <h2>3. Log in</h2>
        {browser ? (
          <ol className="steps">
            <li>
              Open {command("playlist-diff")} or {command("playlist-export")}, paste the client ID into the{" "}
              <strong>Spotify login</strong> box at the top, and click <strong>Log in to Spotify</strong>.
            </li>
            <li>
              Spotify shows your app&apos;s name and asks to let it see your private and collaborative playlists. Agree,
              and Spotify sends you back here, logged in.
            </li>
            <li>
              <strong>Log in before choosing a folder.</strong> The login takes the whole tab to Spotify and back, which
              reloads this page, and a reload forgets picked folders and this tab&apos;s reports.
            </li>
            <li>
              That was the last time. The login stays in this browser, renewed in the background, until you click{" "}
              <strong>Log out</strong>, and other tabs share it. Paste a playlist link into the form and run.
            </li>
          </ol>
        ) : (
          <ol className="steps">
            <li>
              Give sdm the client ID. Either once, for every run — in a terminal:
              <CopyLine text={SETX} />
              then start <code>sdm web</code> again from a new terminal, since <code>setx</code> reaches only new ones.
              Or paste it into <code>--client-id</code> on the form each time.
            </li>
            <li>
              Run the command with a playlist link. sdm opens Spotify&apos;s login in a new browser tab; if none opens,
              the job&apos;s log has the link. Spotify shows your app&apos;s name and asks to let it see your private and
              collaborative playlists. Agree, and that tab says you can close it.
            </li>
            <li>
              Spotify asks only the first time; after that the login comes straight back. It is not kept between runs,
              so to diff one playlist again and again, export it once with {command("playlist-export")} and give{" "}
              <code>playlist-diff</code> the CSV: no login at all.
            </li>
            <li>
              If port 8765 is taken, register another loopback address on the app, such as{" "}
              <code>http://127.0.0.1:8766/callback</code>, and set <code>SDM_SPOTIFY_REDIRECT_URI</code> to it. One
              registered without a port, <code>http://127.0.0.1/callback</code>, lets sdm pick a free port each run.
            </li>
          </ol>
        )}
      </section>

      <section id="playlists">
        <h2>Which playlists it can read</h2>
        <p>
          Only playlists you <strong>own or collaborate on</strong>. That is Spotify&apos;s rule for every app since
          February 2026, not sdm&apos;s. For anyone else&apos;s playlist — a friend&apos;s, a label&apos;s, an editorial
          one:
        </p>
        <ul>
          <li>
            copy its tracks into a playlist of your own in the Spotify app (select all, <em>Add to playlist</em>) and use
            that link; or
          </li>
          <li>
            export it to CSV with <External to="https://exportify.net/">Exportify</External> and give{" "}
            <code>playlist-diff</code> the CSV, which needs no login at all.
          </li>
        </ul>
      </section>

      <section id="sharing">
        <h2>Letting someone else use your app</h2>
        <p>
          Simplest is for them to make their own. To add them to yours instead: in the app&apos;s{" "}
          <strong>Settings</strong>, open <strong>User Management</strong>, click <strong>Add new user</strong>, and
          enter their name and the email address of their Spotify account, exactly as their account page shows it.
          Spotify allows five users per app. Anyone not on the list can still log in, but Spotify then refuses every
          request.
        </p>
      </section>

      <section id="troubleshooting">
        <h2>If something goes wrong</h2>
        <dl className="faq">
          <dt>
            Spotify&apos;s page says <code>INVALID_CLIENT: Invalid redirect URI</code>
          </dt>
          <dd>
            The app does not have exactly <code>{redirect}</code> among its redirect URIs. Compare it character by
            character, and check that you clicked Add and then Save.
          </dd>
          <dt>
            Spotify&apos;s page says <code>INVALID_CLIENT: Invalid client</code>
          </dt>
          <dd>The client ID is mistyped, or the app was deleted. Copy it again from the app&apos;s Settings.</dd>
          <dt>
            {browser
              ? "“Spotify logged you in, but refuses to answer for this account”"
              : "“Spotify answered 403”, mentioning that the user may not be registered"}
          </dt>
          <dd>
            The account you logged in with is not the app&apos;s owner and not on its{" "}
            <a href={href("/spotify", { section: "sharing" })}>User Management</a> list, or the owner&apos;s Premium has
            lapsed. If Spotify logged you in as someone else, log out at spotify.com and try again.
          </dd>
          <dt>&ldquo;Spotify will not list the tracks of …&rdquo;</dt>
          <dd>
            The playlist is not yours or shared with you as a collaborator: see{" "}
            <a href={href("/spotify", { section: "playlists" })}>which playlists it can read</a>.
          </dd>
          <dt>{browser ? "“The Spotify login was cancelled”" : "“access_denied (cancelled in the browser)”"}</dt>
          <dd>You clicked Cancel on Spotify&apos;s page. Log in again and agree.</dd>
          {browser ? (
            <>
              <dt>&ldquo;Log in to Spotify above first&rdquo; when you run</dt>
              <dd>
                The login was ended here or in another tab, or could not be renewed; the login box says which. Log in
                again.
              </dd>
            </>
          ) : (
            <>
              <dt>&ldquo;no Spotify login within 180s&rdquo;</dt>
              <dd>
                The login tab was not finished within three minutes. Run again, and if no tab opens, open the link in
                the job&apos;s log.
              </dd>
              <dt>&ldquo;cannot listen on 127.0.0.1:8765&rdquo;</dt>
              <dd>Another program holds the port: see the last step of Log in.</dd>
            </>
          )}
        </dl>
      </section>

      <section id="privacy">
        <h2>What the login allows</h2>
        <ul>
          <li>
            <strong>Reading only.</strong> sdm asks for <code>playlist-read-private</code> and{" "}
            <code>playlist-read-collaborative</code> and nothing more: it can read your playlists, and cannot change,
            create or follow anything, or see your email or listening history.
          </li>
          {browser ? (
            <>
              <li>
                <strong>Your browser talks to Spotify directly</strong>: <code>accounts.spotify.com</code> to log in,{" "}
                <code>api.spotify.com</code> to read a playlist. There is no sdm server in between. The page&apos;s
                security policy lets it connect to this site and those two addresses and nowhere else, so your music
                files still never leave the tab.
              </li>
              <li>
                The login is stored in this browser, in its local storage, until you log out. The client ID is not a
                secret: it is in every login link.
              </li>
            </>
          ) : (
            <li>A login lasts one run: the run&apos;s process holds the token and nothing is saved.</li>
          )}
          <li>
            To withdraw it at any time:{" "}
            <External to="https://www.spotify.com/account/apps/">spotify.com/account/apps</External>, then{" "}
            <strong>Remove access</strong> beside your app. Deleting the app on the dashboard ends it for everyone.
          </li>
        </ul>
        <p className="muted">
          Checked against Spotify&apos;s documentation in October 2026. Spotify changes these rules; if a step looks
          different, its{" "}
          <External to="https://developer.spotify.com/documentation/web-api/concepts/apps">developer documentation</External>{" "}
          is the reference.
        </p>
      </section>
    </div>
  );
}
