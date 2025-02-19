import os
import subprocess

import pytest

__all__ = [
    "make_tmp_dir",
    "tmp_dir",
    "scm",
    "dvc",
    "make_cloud",
    "cloud",
    "make_remote",
    "remote",
    "workspace",
    "make_workspace",
    "docker",
    "docker_compose",
    "docker_compose_project_name",
    "docker_services",
]

CACHE = {}  # type: ignore


def _fs_copy(src, dst, ignore=None):
    import shutil

    if os.path.isdir(src):
        shutil.copytree(src, dst, ignore=ignore)
    else:
        shutil.copy2(src, dst)


@pytest.fixture(scope="session")
def make_tmp_dir(tmp_path_factory, request, worker_id):
    def make(
        name, *, scm=False, dvc=False, subdir=False
    ):  # pylint: disable=W0621
        from shutil import ignore_patterns

        from scmrepo.git import Git

        from dvc.repo import Repo

        from .tmp_dir import TmpDir

        cache = CACHE.get((scm, dvc, subdir))
        if not cache:
            cache = tmp_path_factory.mktemp("dvc-test-cache" + worker_id)
            TmpDir(cache).init(scm=scm, dvc=dvc, subdir=subdir)
            CACHE[(scm, dvc, subdir)] = os.fspath(cache)
        path = tmp_path_factory.mktemp(name) if isinstance(name, str) else name

        # ignore sqlite files from .dvc/tmp. We might not be closing the cache
        # connection resulting in PermissionErrors in Windows.
        ignore = ignore_patterns("cache.db*")
        for entry in os.listdir(cache):
            # shutil.copytree's dirs_exist_ok is only available in >=3.8
            _fs_copy(
                os.path.join(cache, entry),
                os.path.join(path, entry),
                ignore=ignore,
            )
        new_dir = TmpDir(path)
        str_path = os.fspath(new_dir)
        if dvc:
            new_dir.dvc = Repo(str_path)
        if scm:
            new_dir.scm = (
                new_dir.dvc.scm if hasattr(new_dir, "dvc") else Git(str_path)
            )
        request.addfinalizer(new_dir.close)
        return new_dir

    return make


@pytest.fixture
def tmp_dir(tmp_path, make_tmp_dir, request, monkeypatch):
    monkeypatch.chdir(tmp_path)
    fixtures = request.fixturenames
    return make_tmp_dir(tmp_path, scm="scm" in fixtures, dvc="dvc" in fixtures)


@pytest.fixture
def scm(tmp_dir):
    return tmp_dir.scm


@pytest.fixture
def dvc(tmp_dir):
    with tmp_dir.dvc as _dvc:
        yield _dvc


@pytest.fixture
def make_cloud(request):
    def _make_cloud(typ):
        return request.getfixturevalue(f"make_{typ}")()

    return _make_cloud


@pytest.fixture
def cloud(make_cloud, request):
    if not hasattr(request, "param"):
        pytest.skip("no cloud specified")
    return make_cloud(request.param)


@pytest.fixture
def make_remote(tmp_dir, dvc, make_cloud):
    def _make_remote(name, typ="local", **kwargs):
        cloud = make_cloud(typ)  # pylint: disable=W0621
        tmp_dir.add_remote(name=name, config=cloud.config, **kwargs)
        return cloud

    return _make_remote


@pytest.fixture
def remote(make_remote, request):
    if not hasattr(request, "param"):
        pytest.skip("no remote specified")
    return make_remote("upstream", typ=request.param)


@pytest.fixture
def make_workspace(tmp_dir, dvc, make_cloud):
    def _make_workspace(name, typ="local"):
        from dvc.objects.db import ODBManager

        cloud = make_cloud(typ)  # pylint: disable=W0621

        tmp_dir.add_remote(name=name, config=cloud.config, default=False)
        tmp_dir.add_remote(
            name=f"{name}-cache", url="remote://workspace/cache", default=False
        )

        scheme = getattr(cloud, "scheme", "local")
        if scheme != "http":
            with dvc.config.edit() as conf:
                conf["cache"][scheme] = f"{name}-cache"

            dvc.odb = ODBManager(dvc)

        return cloud

    return _make_workspace


@pytest.fixture
def workspace(make_workspace, request):
    if not hasattr(request, "param"):
        pytest.skip("no workspace specified")

    return make_workspace("workspace", typ=request.param)


@pytest.fixture(scope="session")
def docker():
    # See https://travis-ci.community/t/docker-linux-containers-on-windows/301
    if os.environ.get("CI") and os.name == "nt":
        pytest.skip("disabled for Windows on Github Actions")

    try:
        subprocess.check_output("docker ps", shell=True)
    except (subprocess.CalledProcessError, OSError):
        pytest.skip("no docker installed")


@pytest.fixture(scope="session")
def docker_compose(docker):
    try:
        subprocess.check_output("docker-compose version", shell=True)
    except (subprocess.CalledProcessError, OSError):
        pytest.skip("no docker-compose installed")


@pytest.fixture(scope="session")
def docker_compose_project_name():
    return "pytest-dvc-test"


@pytest.fixture(scope="session")
def docker_services(
    docker_compose_file, docker_compose_project_name, tmp_path_factory
):
    # overriding `docker_services` fixture from `pytest_docker` plugin to
    # only launch docker images once.

    from filelock import FileLock
    from pytest_docker.plugin import DockerComposeExecutor, Services

    executor = DockerComposeExecutor(
        docker_compose_file, docker_compose_project_name
    )

    # making sure we don't accidentally launch docker-compose in parallel,
    # as it might result in network conflicts. Inspired by:
    # https://github.com/pytest-dev/pytest-xdist#making-session-scoped-fixtures-execute-only-once
    lockfile = tmp_path_factory.getbasetemp().parent / "docker-compose.lock"
    with FileLock(str(lockfile)):  # pylint:disable=abstract-class-instantiated
        executor.execute("up --build -d")

    return Services(executor)
