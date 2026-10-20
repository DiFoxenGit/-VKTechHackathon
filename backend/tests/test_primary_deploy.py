"""Exercise deployment failure boundaries without SSH, Docker or provider calls."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHA = 'a' * 40
PREVIOUS = 'b' * 40
pytestmark = pytest.mark.skipif(sys.platform == 'win32' or not shutil.which('bash'), reason='Linux deployment shell')


@pytest.mark.parametrize('value', ['', 'deploy main', 'deploy ' + SHA + ' extra', 'deploy ' + SHA + '\nid', 'shell ' + SHA])
def test_restricted_key_rejects_arbitrary_commands(value):
    result = subprocess.run(['bash', str(ROOT / 'deploy/primary-receive.sh')],
                            env={**os.environ, 'SSH_ORIGINAL_COMMAND': value}, capture_output=True, timeout=5)
    assert result.returncode == 2


@pytest.fixture
def deployment(tmp_path):
    app = tmp_path / 'app'
    runtime = tmp_path / 'runtime'
    bins = tmp_path / 'bin'
    for folder in [app, runtime, bins]:
        folder.mkdir()
    (app / 'deploy').mkdir()
    shutil.copy(ROOT / 'deploy/primary-deploy.sh', app / 'deploy/primary-deploy.sh')
    shutil.copy(ROOT / 'deploy/runtime_profile.py', app / 'deploy/runtime_profile.py')
    shutil.copy(ROOT / 'deploy/backup_database.py', app / 'deploy/backup_database.py')
    (app / 'deploy/autosell-nginx.conf').write_text('new nginx')
    (app / '.env.autosell').write_text('DESIGNER_LLM_PROVIDER=openai\nDESIGNER_LLM_API_KEY=old-value\n')
    (app / 'nginx.conf').write_text('old nginx')
    (app / '.env').write_text('existing setting\n')
    (runtime / 'genapi.compose.json').write_text('{"private":"preserved"}\n')
    log = tmp_path / 'commands'
    scripts = {
        'git': f'''#!/bin/bash
echo "git $*" >> "$COMMAND_LOG"
case "$1" in
 status) [ "${{DIRTY:-0}}" = 0 ] || echo ' M tracked';;
 rev-parse) echo {PREVIOUS};;
 merge-base) [[ "${{4:-}}" = refs/remotes/github/main || "${{4:-}}" = origin/main ]] && [ "${{FOREIGN:-0}}" = 0 ];;
esac
''',
        'docker': '''#!/bin/bash
echo "docker $*" >> "$COMMAND_LOG"
case "$*" in
 *'ps -q backend'*) echo backend-id;;
 *'ps -q frontend'*) echo frontend-id;;
 'inspect '*) echo sha256:running-image;;
 *'build backend'*) [ "${FAIL_BUILD:-0}" = 0 ];;
 *'exec -T backend python '*) cat >/dev/null; [ "${ACTIVE:-0}" = 0 ];;
esac
''',
        'curl': '#!/bin/bash\necho "curl $*" >> "$COMMAND_LOG"\n[ "${FAIL_HEALTH:-0}" = 0 ]\n',
        'nginx': '#!/bin/bash\nexit 0\n',
    }
    for name, text in scripts.items():
        script = bins / name
        script.write_text(text)
        script.chmod(0o755)
    env = {**os.environ, 'PATH': str(bins) + os.pathsep + os.environ['PATH'],
           'APP_DIR': str(app), 'RUNTIME_DIR': str(runtime), 'COMMAND_LOG': str(log),
           'NGINX_SNIPPET': str(app / 'nginx.conf')}

    def run(script='primary-deploy.sh', input_text='', **settings):
        result = subprocess.run(['bash', str(ROOT / 'deploy' / script), SHA], input=input_text,
                                env={**env, **settings}, capture_output=True, text=True, timeout=10)
        return result, log.read_text() if log.exists() else ''
    return run, app, runtime


def test_success_preserves_private_config_and_targets_tested_commit(deployment):
    run, app, runtime = deployment
    result, log = run()
    assert result.returncode == 0, result.stderr
    assert (app / '.env').read_text() == 'existing setting\n'
    assert (runtime / 'genapi.compose.json').read_text() == '{"private":"preserved"}\n'
    assert (runtime / 'deployed-main.sha').read_text().strip() == SHA
    assert 'https://github.com/DiFoxenGit/-VKTechHackathon.git' in log
    assert f'checkout --quiet --detach {SHA}' in log
    assert log.index('build backend') < log.index('build frontend') < log.index('up -d')
    assert log.count('genapi.compose.json') >= 4
    assert 'reset --hard' not in log and 'prune' not in log


@pytest.mark.parametrize('failure', ['DIRTY', 'FOREIGN'])
def test_untrusted_commit_or_local_changes_never_build(deployment, failure):
    run, _, _ = deployment
    result, log = run(**{failure: '1'})
    assert result.returncode != 0
    assert 'build backend' not in log and 'up -d' not in log


@pytest.mark.parametrize('failure', ['FAIL_BUILD', 'ACTIVE'])
def test_failure_before_restart_restores_checkout_without_interrupting_server(deployment, failure):
    run, _, runtime = deployment
    result, log = run(**{failure: '1'})
    assert result.returncode != 0
    assert f'checkout --quiet --detach {PREVIOUS}' in log
    assert 'up -d' not in log
    assert not (runtime / 'deployed-main.sha').exists()


def test_failed_health_restores_running_images_and_checkout(deployment):
    run, _, runtime = deployment
    result, log = run(FAIL_HEALTH='1')
    assert result.returncode != 0
    assert f'checkout --quiet --detach {PREVIOUS}' in log
    assert f'vk-designer-backend:before-{SHA} vk-designer-backend:latest' in log
    assert log.count('up -d') == 2
    assert not (runtime / 'deployed-main.sha').exists()


@pytest.mark.parametrize('failed', [False, True])
def test_autosell_applies_profile_and_restores_original_env_on_failure(deployment, failed):
    run, app, _ = deployment
    original = (app / '.env.autosell').read_bytes()
    result, _ = run(script='autosell-deploy.sh',
                    input_text='{"DESIGNER_LLM_PROVIDER":"vk","DESIGNER_VK_API_KEY":"new-private-value"}',
                    FAIL_HEALTH='1' if failed else '0')
    assert (result.returncode != 0) is failed, result.stderr
    if failed:
        assert (app / '.env.autosell').read_bytes() == original
        assert (app / 'nginx.conf').read_text() == 'old nginx'
    else:
        assert "DESIGNER_LLM_PROVIDER='vk'" in (app / '.env.autosell').read_text()
        assert 'DESIGNER_LLM_API_KEY=old-value' in (app / '.env.autosell').read_text()
    assert 'new-private-value' not in result.stdout + result.stderr
    backup = next((app / 'tmp/deploy-backups').glob('*/server.env'))
    assert backup.read_bytes() == original
    assert backup.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('failure', ['FAIL_BUILD', 'ACTIVE'])
def test_autosell_pre_restart_failure_preserves_running_containers_and_env(deployment, failure):
    run, app, _ = deployment
    original = (app / '.env.autosell').read_bytes()
    result, log = run(script='autosell-deploy.sh', input_text='{"DESIGNER_LLM_PROVIDER":"vk"}', **{failure: '1'})
    assert result.returncode != 0
    assert 'up -d' not in log
    assert (app / '.env.autosell').read_bytes() == original
