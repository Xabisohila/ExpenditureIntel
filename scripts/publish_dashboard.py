import os
import shutil
import subprocess
import sys

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), '..')
PROCESSED_DIR = os.path.join(PROJECT_ROOT, 'data', 'processed')
DOCS_DIR = os.path.join(PROJECT_ROOT, 'docs')

# (source path, destination path, git path relative to PROJECT_ROOT)
FILES_TO_PUBLISH = [
    (os.path.join(PROCESSED_DIR, 'dashboard.html'), os.path.join(DOCS_DIR, 'index.html'), 'docs/index.html'),
    (os.path.join(PROCESSED_DIR, 'commitments.csv'), os.path.join(DOCS_DIR, 'data', 'commitments.csv'), 'docs/data/commitments.csv'),
    (os.path.join(PROCESSED_DIR, 'expenditure.csv'), os.path.join(DOCS_DIR, 'data', 'expenditure.csv'), 'docs/data/expenditure.csv'),
]


def run(*cmd, capture=True):
    result = subprocess.run(cmd, cwd=PROJECT_ROOT, capture_output=capture, text=True)
    if capture:
        print(result.stdout, end='')
        if result.returncode != 0:
            print(result.stderr, end='', file=sys.stderr)
    return result.returncode


def main():
    missing = [src for src, _, _ in FILES_TO_PUBLISH if not os.path.exists(src)]
    if missing:
        print(f"Missing source file(s): {missing}")
        print("Run scripts/build_dataset.py and scripts/build_dashboard.py (or ingest_week.py) first.")
        return False

    git_paths = []
    for src, dest, git_path in FILES_TO_PUBLISH:
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        shutil.copyfile(src, dest)
        print(f"Copied {src} -> {dest}")
        git_paths.append(git_path)

    run('git', 'add', *git_paths)
    # Compare the now-staged files against HEAD (not the working tree, which
    # `git diff` alone would use) so a brand-new untracked file on the very
    # first publish is correctly seen as "changed" rather than silently
    # skipped.
    unchanged = run('git', 'diff', '--cached', '--quiet', '--', *git_paths) == 0
    if unchanged:
        print("\nNothing changed since the last publish -- nothing to commit.")
        return True

    commit_rc = run('git', 'commit', '-m',
                     'Publish updated dashboard and data\n\nCo-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>')
    if commit_rc == 0:
        print("\nCommitted. This does NOT push automatically -- run 'git push origin master' "
              "(or ask me to) to make the update live.")
    return commit_rc == 0


if __name__ == '__main__':
    main()
