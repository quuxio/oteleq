import os
import subprocess
import sys

GH = '/opt/homebrew/bin/gh'
env = os.environ.copy()
for key in ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN'):
    env.pop(key, None)
token_result = subprocess.run([GH, 'auth', 'token', '--hostname', 'github.com', '--user', 'quuxio'], env=env, capture_output=True, text=True)
if token_result.returncode or not token_result.stdout.strip():
    sys.exit('The saved quuxio GitHub credential is unavailable.')
env['GH_TOKEN'] = token_result.stdout.strip()
identity = subprocess.run([GH, 'api', 'user', '--jq', '.login'], env=env, capture_output=True, text=True)
if identity.returncode or identity.stdout.strip() != 'quuxio':
    sys.exit('The GitHub API identity is not verified as quuxio.')
if len(sys.argv) > 1 and sys.argv[1] == '--git':
    command = ['git', '-c', 'credential.helper=', '-c', 'credential.helper=!/opt/homebrew/bin/gh auth git-credential', *sys.argv[2:]]
else:
    command = [GH, *sys.argv[1:]]
result = subprocess.run(command, env=env)
sys.exit(result.returncode)
