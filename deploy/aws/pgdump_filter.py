#!/usr/bin/env python3
"""Stream a trusted, plain pg_dump .sql.gz to stdout for restore into RDS.

This is NOT a SQL sanitizer. Only use trusted backups made by your own project.
Ownership and ACL commands from a local PostgreSQL superuser are removed;
new least-privilege grants are installed after the restore.
"""
import gzip
import re
import sys

OWNER = re.compile(rb'^ALTER\s+.+\s+OWNER\s+TO\s+.+;\s*$', re.I)
ACL = re.compile(rb'^(?:GRANT|REVOKE|ALTER\s+DEFAULT\s+PRIVILEGES)\b', re.I)
DANGEROUS = re.compile(rb'^\s*(?:CREATE|DROP)\s+DATABASE\b', re.I)


def filter_lines(source, destination):
    in_copy = False
    for line in source:
        if in_copy:
            destination.write(line)
            if line.rstrip(b'\r\n') == b'\\.':
                in_copy = False
            continue
        clean = line.strip()
        if clean.lower().startswith(b'copy ') and b' from stdin;' in clean.lower():
            in_copy = True
            destination.write(line)
            continue
        # Newer pg_dump versions may emit the harmless \\restrict and \\unrestrict.
        if clean.startswith(b'\\') and not (clean.startswith(b'\\restrict ') or clean.startswith(b'\\unrestrict ')):
            raise ValueError('Unexpected psql meta-command outside COPY: ' + repr(clean[:100]))
        if DANGEROUS.match(clean) or clean.upper().startswith(b'SET SESSION AUTHORIZATION'):
            raise ValueError('Database-level/ownership command requires a clean dump: ' + repr(clean[:100]))
        if OWNER.match(clean) or ACL.match(clean):
            continue
        destination.write(line)
    if in_copy:
        raise ValueError('Incomplete COPY section')


def main():
    if len(sys.argv) != 2:
        raise SystemExit('Usage: pgdump_filter.py database/moviedb.sql.gz')
    with gzip.open(sys.argv[1], 'rb') as source:
        filter_lines(source, sys.stdout.buffer)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as exc:
        print('pgdump_filter failed: ' + str(exc), file=sys.stderr)
        sys.exit(1)
