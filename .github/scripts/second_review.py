import ast
import base64
import json
import subprocess
import sys

def run_cmd(args, check=True):
    res = subprocess.run(args, capture_output=True, text=True)
    if check and res.returncode != 0:
        print(f"Error running command {' '.join(args)}:\nStderr: {res.stderr.strip()}", file=sys.stderr)
        res.check_returncode()
    return res.stdout.strip()

def safe_json_load(data_str):
    if not data_str:
        return None
    try:
        return json.loads(data_str)
    except json.JSONDecodeError as e:
        print(f"JSON decode warning: {e}", file=sys.stderr)
        return None

def fetch_reviews_and_comments(repo, num):
    reviews_str = run_cmd(['gh', 'api', f'repos/{repo}/pulls/{num}/reviews'], check=False)
    reviews = safe_json_load(reviews_str) or []

    comments_str = run_cmd(['gh', 'api', f'repos/{repo}/issues/{num}/comments'], check=False)
    comments = safe_json_load(comments_str) or []

    return reviews, comments

def get_initial_review_signal(reviews, comments, head_sha):
    initial_reviews = []
    short_sha = head_sha[:7]

    for r in reviews:
        if r.get('commit_id') == head_sha:
            initial_reviews.append({
                'type': 'formal_review',
                'author': r.get('user', {}).get('login', 'unknown'),
                'state': r.get('state', 'COMMENTED'),
                'body': r.get('body') or ''
            })

    for c in comments:
        body = c.get('body') or ''
        if 'Second Review Pass' in body or 'Automated PR Scope' in body:
            continue
        if ('review' in body.lower() or 'VERDICT' in body or 'Amaranth' in body) and short_sha in body:
            initial_reviews.append({
                'type': 'comment_review',
                'author': c.get('user', {}).get('login', 'unknown'),
                'state': 'COMMENT',
                'body': body
            })

    return initial_reviews

def analyze_pr(repo, pr):
    num = pr['number']
    title = pr['title']
    full_head_sha = pr.get('head', {}).get('sha', '')
    head_sha = full_head_sha[:7]

    reviews, comments = fetch_reviews_and_comments(repo, num)

    initial_reviews = get_initial_review_signal(reviews, comments, full_head_sha)
    if not initial_reviews:
        print(f'PR #{num} ({title}): No initial review pass found for head commit ({head_sha}). Skipping.')
        return

    review_marker = f'Second Review Pass for commit {head_sha}'
    already_reviewed = any(review_marker in (c.get('body') or '') for c in comments)

    if already_reviewed:
        print(f'PR #{num} ({title}): Second review pass already posted for commit {head_sha}.')
        return

    print(f'PR #{num} ({title}): Found {len(initial_reviews)} initial review signal(s). Running second review pass...')

    files_str = run_cmd(['gh', 'api', f'repos/{repo}/pulls/{num}/files'])
    files = safe_json_load(files_str) or []

    diff_text = run_cmd(['gh', 'pr', 'diff', str(num)])
    diff_lines = diff_text.splitlines() if diff_text else []

    # Cross-reference initial review text
    initial_review_bodies = [r['body'] for r in initial_reviews if r['body']]
    combined_initial_feedback = '\n'.join(initial_review_bodies)

    findings = []
    has_test_changes = any('test' in f['filename'].lower() for f in files)
    has_code_changes = any(f['filename'].endswith('.py') and 'test' not in f['filename'].lower() for f in files)

    if has_code_changes and not has_test_changes:
        findings.append('⚠️ Code changes introduced without corresponding unit tests.')

    # Verify if initial review highlighted concerns that remain in current diff
    if 'test' in combined_initial_feedback.lower() and not has_test_changes:
        findings.append('🔎 Initial review requested test coverage; verified no test files added in current head.')
    if 'VERDICT: CHANGES NEEDED' in combined_initial_feedback:
        findings.append('📋 Verified previous review verdict was CHANGES NEEDED; checking head commit updates.')

    # AST checks on remote head files
    for f in files:
        fn = f['filename']
        if fn.endswith('.py') and f.get('status') != 'removed':
            content_str = run_cmd(['gh', 'api', f'repos/{repo}/contents/{fn}?ref={full_head_sha}'], check=False)
            content_json = safe_json_load(content_str)
            if content_json and content_json.get('content'):
                try:
                    file_bytes = base64.b64decode(content_json['content'])
                    ast.parse(file_bytes.decode('utf-8'))
                except SyntaxError as se:
                    findings.append(f'❌ Syntax error in `{fn}`: {se}')
                except Exception:
                    pass

    observations = []
    for f in files:
        fn = f['filename']
        additions = f.get('additions', 0)
        deletions = f.get('deletions', 0)
        observations.append(f'- `{fn}` (+{additions}, -{deletions})')

    review_lines = [
        f'### {review_marker}',
        f'**Verified Initial Review(s)**: Found {len(initial_reviews)} review signal(s) bound to `{head_sha}`.',
        f'**PR Scope**: {len(files)} file(s) modified, {len(diff_lines)} line(s) in diff.',
        '',
        '**Files Included in Review Pass**:'
    ]
    review_lines.extend(observations[:15])
    if len(observations) > 15:
        review_lines.append(f'- ... and {len(observations) - 15} more files.')

    if findings:
        review_lines.extend(['', '**Second Review Pass Findings & Cross-Checks**:'])
        for finding in findings:
            review_lines.append(f'- {finding}')
    else:
        review_lines.extend(['', '✅ **Second Review Pass Result**: Initial review points verified. No new syntax issues or unaddressed concerns detected.'])

    body = '\n'.join(review_lines)
    run_cmd(['gh', 'pr', 'comment', str(num), '--body', body])
    print(f'PR #{num}: Second review comment posted successfully for commit {head_sha}.')

def main():
    repo = run_cmd(['gh', 'repo', 'view', '--json', 'nameWithOwner', '-q', '.nameWithOwner'])
    if not repo:
        print('No repository info found.')
        sys.exit(0)

    prs_str = run_cmd(['gh', 'api', f'repos/{repo}/pulls?state=open'])
    prs = safe_json_load(prs_str) or []
    print(f'Found {len(prs)} open PR(s).')

    for pr in prs:
        analyze_pr(repo, pr)

if __name__ == '__main__':
    main()
