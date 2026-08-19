"""Feature packages.

Each subpackage owns one tool and exposes `add_parser(subparsers)`. A feature
may import from `sdm.core`; it must never import from a sibling feature.

`add_parser` must stay cheap — argparse only. Third-party imports belong inside
the command handler so that `sdm --help` works without every optional
dependency installed.
"""
