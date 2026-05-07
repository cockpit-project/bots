import asyncio
import contextlib
import json
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import AsyncGenerator
from unittest.mock import AsyncMock, Mock, patch

import pytest
from yarl import URL

from lib.aio.github import GitHub
from lib.aio.job import Failure, Job, run_job
from lib.aio.jsonutil import JsonObject, get_str, typechecked
from lib.aio.local import LocalLogDriver
from lib.test_mock_server import MockHandler, MockServer


@contextlib.asynccontextmanager
async def _async_cm(value: Mock) -> AsyncIterator[Mock]:  # noqa: RUF029
    yield value


ADDRESS = ("127.0.0.1", 9999)

# Global path for recording POST calls across processes
POST_CALLS_FILE = Path(tempfile.gettempdir()) / "test_job_post_calls.json"

# Mock GitHub API responses
GITHUB_DATA: JsonObject = {
    "/repos/cockpit-project/cockpit/git/refs/heads/main": {
        "object": {"sha": "abc123def456789012345678901234567890abcd"}
    },
    "/repos/cockpit-project/cockpit/pulls/42": {
        "state": "open",
        "head": {"sha": "abc123def456789012345678901234567890abcd"},
        "base": {"ref": "main"}
    },
    "/repos/cockpit-project/cockpit/contents/.cockpit-ci/container": {
        "content": "Y29ja3BpdC1wcm9qZWN0L2Nvc3RvbS1pbWFnZQo="  # base64 of "cockpit-project/custom-image\n"
    }
}


class MockGitHubHandler(MockHandler[JsonObject]):
    @staticmethod
    def clear_post_calls() -> None:
        POST_CALLS_FILE.unlink(missing_ok=True)

    @staticmethod
    def get_post_calls() -> list[tuple[str, JsonObject]]:
        try:
            return json.loads(POST_CALLS_FILE.read_text())
        except FileNotFoundError:
            return []

    def do_GET(self) -> None:
        data = self.server.data
        if self.path in data:
            self.replyJson(data[self.path])
        else:
            self.send_error(404, f'Mock Not Found: {self.path}')

    def do_POST(self) -> None:
        # Parse request body
        content_length = int(self.headers.get('Content-Length', '0'))
        post_body = self.rfile.read(content_length)
        post_data = typechecked(json.loads(post_body.decode('utf-8')), dict)

        # Record the POST call to file
        existing_calls = self.get_post_calls()
        existing_calls.append((self.path, post_data))
        with POST_CALLS_FILE.open('w') as f:
            json.dump(existing_calls, f)

        if self.path.startswith('/repos/') and '/statuses/' in self.path:
            # Mock status posting
            self.replyJson({"state": "success", "context": "test"})
        elif self.path.startswith('/repos/') and self.path.endswith('/issues'):
            # Mock issue creation
            self.replyJson({"number": 123, "title": "Test Issue"})
        else:
            self.send_error(404, f'Mock Not Found: {self.path}')


@pytest.fixture
def mock_log() -> Mock:
    log = Mock()
    log.url = URL('http://localhost:9000/test-job/log.html')
    log.start = Mock()
    log.write = Mock()
    log.write_attachment = Mock()
    log.close = Mock()
    return log


@pytest.fixture
async def mock_job_context(tmp_path: Path) -> AsyncGenerator[Mock, None]:
    """Mock JobContext with mock GitHub forge"""

    # Clear any previous POST calls from other tests
    MockGitHubHandler.clear_post_calls()

    server = MockServer(ADDRESS, MockGitHubHandler, GITHUB_DATA)
    server.start()

    try:
        github_config: JsonObject = {
            'clone-url': f'http://{ADDRESS[0]}:{ADDRESS[1]}/',
            'api-url': f'http://{ADDRESS[0]}:{ADDRESS[1]}/',
            'user-agent': 'test-runner',
            'post': True,  # Enable actual POST requests
            'token': 'dummy-token'  # Required when post is True
        }

        log_config: JsonObject = {
            'dir': str(tmp_path),
            'link': 'http://localhost:9000/logs/'
        }

        forge = GitHub('fakehub', github_config)
        await forge.__aenter__()

        logs = LocalLogDriver(log_config)
        await logs.__aenter__()

        # Create mock context with real forge and logs
        mock_ctx = Mock()
        mock_ctx.logs = logs
        mock_ctx.debug = False
        mock_ctx.default_image = 'registry.fedoraproject.org/fedora:latest'
        mock_ctx.container_cmd = ['podman']
        mock_ctx.container_run_args = ['--pull=newer']
        mock_ctx.secrets_args = {}
        mock_ctx.resolve_subject = AsyncMock(wraps=forge.resolve_subject)

        yield mock_ctx

    finally:
        server.kill()
        if 'forge' in locals():
            await forge.__aexit__(None, None, None)
        if 'logs' in locals():
            await logs.__aexit__(None, None, None)


def test_job_minimal() -> None:
    job_data: JsonObject = {
        'repo': 'cockpit-project/cockpit',
        'sha': 'abc123'
    }
    job = Job(job_data)

    assert job.subject.repo == 'cockpit-project/cockpit'
    assert job.subject.sha == 'abc123'
    assert job.container is None
    assert job.command_subject is None
    assert job.secrets == ()
    assert job.command is None
    assert job.env == {}
    assert job.timeout == 120
    assert job.context is None
    assert job.slug is None
    assert job.title is None
    assert job.report is None


class TestRunJob:
    @pytest.fixture
    def basic_job(self) -> Job:
        return Job({
            'repo': 'cockpit-project/cockpit',
            'sha': 'abc123',
            'context': 'verify/rhel-9'
        })

    @pytest.fixture
    def job_with_timeout(self) -> Job:
        return Job({
            'repo': 'cockpit-project/cockpit',
            'sha': 'abc123',
            'context': 'verify/rhel-9',
            'timeout': 1  # 1 minute timeout for testing
        })

    @pytest.fixture
    def job_with_pull(self) -> Job:
        return Job({
            'repo': 'cockpit-project/cockpit',
            'sha': 'abc123',
            'pull': 42,
            'context': 'verify/rhel-9'
        })

    @pytest.fixture
    def job_with_report(self) -> Job:
        return Job({
            'repo': 'cockpit-project/cockpit',
            'sha': 'abc123',
            'context': 'verify/rhel-9',
            'report': {
                'labels': ['test-failure'],
                'assignees': ['maintainer']
            }
        })

    @patch('lib.aio.job.run_container')
    async def test_run_job_success(
        self,
        mock_run_container: AsyncMock,
        basic_job: Job,
        mock_log: Mock,
        mock_job_context: Mock,
    ) -> None:
        mock_run_container.return_value = None
        mock_job_context.logs.get_log = lambda slug: _async_cm(mock_log)

        await run_job(basic_job, mock_job_context)
        mock_run_container.assert_called_once()

        # Verify status posts were made
        post_calls = MockGitHubHandler.get_post_calls()
        assert len(post_calls) == 2

        # First call is the 'pending' status
        pending_path, pending_data = post_calls[0]
        assert pending_path == '/repos/cockpit-project/cockpit/statuses/abc123'
        assert pending_data['state'] == 'pending'
        assert get_str(pending_data, 'description').startswith('In progress')
        assert pending_data['target_url'] == 'http://localhost:9000/test-job/log.html'

        # Second call is the 'success' status
        success_path, success_data = post_calls[1]
        assert success_path == '/repos/cockpit-project/cockpit/statuses/abc123'
        assert success_data['state'] == 'success'
        assert get_str(success_data, 'description').startswith('Success')
        assert success_data['target_url'] == 'http://localhost:9000/test-job/log.html'

    @patch('lib.aio.job.run_container')
    async def test_run_job_failure(
        self,
        mock_run_container: AsyncMock,
        basic_job: Job,
        mock_log: Mock,
        mock_job_context: Mock,
    ) -> None:
        """Test job execution with container failure"""
        mock_run_container.side_effect = Failure('Container exited with code 1')
        mock_job_context.logs.get_log = lambda slug: _async_cm(mock_log)

        await run_job(basic_job, mock_job_context)

        # Verify log was written
        mock_log.write.assert_called_with(
            '\n*** Failure: Container exited with code 1\n'
        )

        # Verify status posts were made
        post_calls = MockGitHubHandler.get_post_calls()
        assert len(post_calls) == 2

        # First call is the 'pending' status
        pending_path, pending_data = post_calls[0]
        assert pending_path == '/repos/cockpit-project/cockpit/statuses/abc123'
        assert pending_data['state'] == 'pending'

        # Second call is the 'failure' status
        failure_path, failure_data = post_calls[1]
        assert failure_path == '/repos/cockpit-project/cockpit/statuses/abc123'
        assert failure_data['state'] == 'failure'
        assert get_str(failure_data, 'description').startswith('Container exited with code 1')
        assert failure_data['target_url'] == 'http://localhost:9000/test-job/log.html'

    @patch('lib.aio.job.run_container')
    async def test_run_job_failure_with_report(
        self,
        mock_run_container: AsyncMock,
        job_with_report: Job,
        mock_log: Mock,
        mock_job_context: Mock,
    ) -> None:
        """Test job execution with failure and issue reporting"""
        mock_run_container.side_effect = Failure('Container exited with code 1')
        mock_job_context.logs.get_log = lambda slug: _async_cm(mock_log)

        await run_job(job_with_report, mock_job_context)

        # Verify status posts were made
        post_calls = MockGitHubHandler.get_post_calls()
        assert len(post_calls) == 3

        # First two are the status updates
        pending_path, pending_data = post_calls[0]
        assert pending_path == '/repos/cockpit-project/cockpit/statuses/abc123'
        assert isinstance(pending_data, dict)
        assert pending_data['state'] == 'pending'

        failure_path, failure_data = post_calls[1]
        assert failure_path == '/repos/cockpit-project/cockpit/statuses/abc123'
        assert isinstance(failure_data, dict)
        assert failure_data['state'] == 'failure'
        assert get_str(failure_data, 'description').startswith('Container exited with code 1')
        assert failure_data['target_url'] == 'http://localhost:9000/test-job/log.html'

        # Third is issue creation
        issue_path, issue_data = post_calls[2]
        assert issue_path == '/repos/cockpit-project/cockpit/issues'
        assert issue_data == {
            'assignees': ['maintainer'],
            'body': 'The job `verify/rhel-9` failed on commit abc123.\n\n'
                    'Log: http://localhost:9000/test-job/log.html\n',
            'labels': ['test-failure'],
            'title': 'verify/rhel-9 failed',
        }

    @patch('lib.aio.job.run_container')
    async def test_run_job_cancelled(
        self,
        mock_run_container: AsyncMock,
        basic_job: Job,
        mock_log: Mock,
        mock_job_context: Mock,
    ) -> None:
        """Test job execution with cancellation"""
        mock_run_container.side_effect = asyncio.CancelledError()
        mock_job_context.logs.get_log = lambda slug: _async_cm(mock_log)

        with pytest.raises(asyncio.CancelledError):
            await run_job(basic_job, mock_job_context)

        mock_log.write.assert_called_with(
            '*** Job cancelled\n'
        )

        # Verify status posts were made
        post_calls = MockGitHubHandler.get_post_calls()
        assert len(post_calls) == 2

        # Last call is the 'error' status with 'Cancelled' message
        error_path, error_data = post_calls[-1]
        assert error_path == '/repos/cockpit-project/cockpit/statuses/abc123'
        assert isinstance(error_data, dict)
        assert error_data['state'] == 'error'
        assert get_str(error_data, 'description').startswith('Cancelled')
        assert error_data['target_url'] == 'http://localhost:9000/test-job/log.html'

    @patch('lib.aio.job.run_container')
    async def test_run_job_timeout(
        self,
        mock_run_container: AsyncMock,
        job_with_timeout: Job,
        mock_log: Mock,
        mock_job_context: Mock,
    ) -> None:
        job_with_timeout.timeout = 0.001  # 60ms
        mock_job_context.logs.get_log = lambda slug: _async_cm(mock_log)

        async def nix_und_zwar_langsam(*_: object, **__: object) -> None:
            await asyncio.sleep(float('inf'))
        mock_run_container.side_effect = nix_und_zwar_langsam

        await run_job(job_with_timeout, mock_job_context)
        mock_run_container.assert_called_once()

        mock_log.write.assert_called_with(
            '\n*** Failure: Timeout after 0.001 minutes\n'
        )

        # Verify status posts were made
        post_calls = MockGitHubHandler.get_post_calls()
        assert len(post_calls) == 2

        # Last call is the 'failure' status with timeout message
        failure_path, failure_data = post_calls[-1]
        assert failure_path == '/repos/cockpit-project/cockpit/statuses/abc123'
        assert isinstance(failure_data, dict)
        assert failure_data['state'] == 'failure'
        assert get_str(failure_data, 'description').startswith('Timeout after 0.001 minutes')
        assert failure_data['target_url'] == 'http://localhost:9000/test-job/log.html'

    @patch('lib.aio.job.run_container')
    async def test_run_job_success_with_proxy_url(
        self,
        mock_run_container: AsyncMock,
        basic_job: Job,
        mock_job_context: Mock,
    ) -> None:
        """Test job execution with proxy URL support"""
        mock_run_container.return_value = None

        mock_log = Mock()
        mock_log.url = URL('http://proxy.example.com:8080/test-job/log.html')
        mock_log.start = Mock()
        mock_log.write = Mock()
        mock_log.close = Mock()
        mock_job_context.logs.get_log = lambda slug: _async_cm(mock_log)

        await run_job(basic_job, mock_job_context)
        mock_run_container.assert_called_once()

        # Verify status posts were made with proxy URL
        post_calls = MockGitHubHandler.get_post_calls()
        assert len(post_calls) == 2

        # First call is the 'pending' status
        pending_path, pending_data = post_calls[0]
        assert pending_path == '/repos/cockpit-project/cockpit/statuses/abc123'
        assert isinstance(pending_data, dict)
        assert pending_data['state'] == 'pending'
        # Should use proxy URL for GitHub status links
        assert pending_data['target_url'] == 'http://proxy.example.com:8080/test-job/log.html'

        # Second call is the 'success' status
        success_path, success_data = post_calls[1]
        assert success_path == '/repos/cockpit-project/cockpit/statuses/abc123'
        assert isinstance(success_data, dict)
        assert success_data['state'] == 'success'
        assert success_data['target_url'] == 'http://proxy.example.com:8080/test-job/log.html'
