"""Local Smartlect middleware operations; credentials never leave run/."""
import base64
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / "run/runtime.env"
PROCESS_FILE = ROOT / "run/processes.json"
DATABASES = ("admin", "user", "product", "stock", "cart", "order", "pay", "coupon")
APPS = ("growth-worker", "growth", "user", "product", "stock", "order", "pay", "cart", "coupon", "admin", "gateway", "web-user", "web-admin")
PORTS = {"MYSQL": 13306, "REDIS": 16379, "RABBIT": 15672,
         "RABBIT_MANAGEMENT": 15674, "NACOS": 18848, "SEATA": 18092,
         "GATEWAY": 18080, "GROWTH": 18000, "DASHBOARD": 18501,
         "ADMIN": 18101, "USER": 18105, "PRODUCT": 18106, "STOCK": 18108,
         "CART": 18102, "ORDER": 18104, "PAY": 18103, "COUPON": 18107, "WEB_USER": 18180, "WEB_ADMIN": 18181}


def run(*args, capture=False):
    return subprocess.run(args, cwd=ROOT, check=True, text=True,
                          capture_output=capture).stdout


def parse_env(path):
    return dict(line.split("=", 1) for line in path.read_text().splitlines()
                if line and not line.startswith("#"))


def model_env(path=None):
    path = path or ROOT / "run/model.env"
    if not path.exists():
        return {}
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o777 != 0o600:
        raise RuntimeError("run/model.env must be a regular file with mode 600")
    allowed = {"SMARTLECT_" + field for field in (
        "MODEL_API_KEY", "MODEL_BASE_URL", "MODEL_ID", "EMBEDDING_API_KEY", "EMBEDDING_BASE_URL",
        "EMBEDDING_MODEL", "EMBEDDING_DIMENSIONS", "EMBEDDING_PROVIDER", "RERANK_API_KEY",
        "RERANK_BASE_URL", "RERANK_MODEL", "RERANK_API_FORMAT",
        "JUDGE_API_KEY", "JUDGE_BASE_URL", "JUDGE_MODEL")}
    values = parse_env(path)
    if set(values) - allowed:
        raise RuntimeError("run/model.env contains non-model fields; values suppressed")
    return values


def free_ports(start, offsets=(0,), occupied=None, host="127.0.0.1"):
    occupied = occupied or set()
    for port in range(start, 64000):
        sockets = []
        try:
            if any(port + offset in occupied for offset in offsets):
                continue
            for offset in offsets:
                sock = socket.socket()
                sockets.append(sock)
                sock.bind((host, port + offset))
            return port
        except OSError:
            continue
        finally:
            for sock in sockets:
                sock.close()
    raise RuntimeError(f"No free port above {start}")


def local_ip():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("192.0.2.1", 1))
        return sock.getsockname()[0]


def bootstrap():
    if ENV_FILE.exists():
        env = parse_env(ENV_FILE)
        web_port = env.get('SMARTLECT_WEB_USER_PORT') or str(free_ports(PORTS['WEB_USER'], occupied={
            int(v) for k, v in env.items() if k.endswith('_PORT')}))
        admin_port = env.get('SMARTLECT_WEB_ADMIN_PORT') or str(free_ports(PORTS['WEB_ADMIN'], occupied={
            int(v) for k, v in env.items() if k.endswith('_PORT')} | {int(web_port)}))
        additions = {key: value for key, value in {
            "SMARTLECT_DEMO_ENABLED": "true", "SMARTLECT_DEMO_PASSWORD": secrets.token_hex(24),
            "SMARTLECT_VISITOR_SECRET": secrets.token_hex(32),
            "SMARTLECT_ATTRIBUTION_SECRET": secrets.token_hex(32),
            "SMARTLECT_ALLOWED_ORIGINS": "http://127.0.0.1:" + env["SMARTLECT_GATEWAY_PORT"],
            "SMARTLECT_WEB_USER_PORT": web_port,
            "SMARTLECT_WEB_ADMIN_PORT": admin_port,
        }.items() if key not in env}
        if additions:
            with ENV_FILE.open("a") as target:
                target.write("\n" + "\n".join(f"{key}={value}" for key, value in additions.items()) + "\n")
            print("Added missing Smartlect demo configuration; existing credentials and ports are unchanged.")
        else:
            print("Keeping existing Smartlect credentials and ports: run/runtime.env")
        origins = env.get('SMARTLECT_ALLOWED_ORIGINS', 'http://127.0.0.1:' + env['SMARTLECT_GATEWAY_PORT']).split(',')
        required_origins = ['http://127.0.0.1:' + port for port in (web_port, admin_port)]
        missing = [origin for origin in required_origins if origin not in origins]
        if missing:
            with ENV_FILE.open('a') as target:
                target.write('\nSMARTLECT_ALLOWED_ORIGINS=' + ','.join([*origins, *missing]) + '\n')
        return
    ENV_FILE.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if run("git", "check-ignore", "run/runtime.env", capture=True).strip() != "run/runtime.env":
        raise RuntimeError("run/runtime.env must be ignored by Git")
    env = {
        "SMARTLECT_MYSQL_HOST": "127.0.0.1", "SMARTLECT_MYSQL_USER": "smartlect_app",
        "SMARTLECT_FLYWAY_USER": "smartlect_flyway",
        "SMARTLECT_REDIS_HOST": "127.0.0.1", "SMARTLECT_REDIS_USERNAME": "",
        "SMARTLECT_REDIS_DB": "0", "SMARTLECT_RABBIT_HOST": "127.0.0.1",
        "SMARTLECT_RABBIT_USER": "smartlect", "SMARTLECT_RABBIT_VHOST": "smartlect",
        "SMARTLECT_NACOS_USERNAME": "nacos", "SMARTLECT_NACOS_NAMESPACE": "",
        "SMARTLECT_NACOS_GROUP": "SMARTLECT_GROUP", "SMARTLECT_SEATA_IP": local_ip(),
        "SMARTLECT_SEATA_GROUP": "SMARTLECT_SEATA_GROUP",
        "SMARTLECT_SEATA_TX_GROUP": "smartlect_tx_group",
        "SMARTLECT_GROWTH_MYSQL_USER": "smartlect_growth",
        "SMARTLECT_GROWTH_MYSQL_DATABASE": "smartlect_growth",
        "SMARTLECT_MODEL_MODE": "mock", "SMARTLECT_PAYMENT_MODE": "mock", "SMARTLECT_DEMO_ENABLED": "true",
        "SMARTLECT_GROWTH_EVENTS_ENABLED": "true",
    }
    for key in ("MYSQL_ROOT_PASSWORD", "MYSQL_PASSWORD", "FLYWAY_PASSWORD",
                "REDIS_PASSWORD", "RABBIT_PASSWORD", "NACOS_PASSWORD",
                "NACOS_MYSQL_PASSWORD", "NACOS_IDENTITY", "SEATA_MYSQL_PASSWORD",
                "SEATA_SECRET", "INTERNAL_TOKEN", "INTERNAL_OPS_TOKEN",
                "GROWTH_MYSQL_PASSWORD", "ADMIN_PASSWORD", "DEMO_PASSWORD", "VISITOR_SECRET", "ATTRIBUTION_SECRET"):
        env[f"SMARTLECT_{key}"] = secrets.token_hex(24)
    env["SMARTLECT_NACOS_AUTH_TOKEN"] = base64.b64encode(secrets.token_bytes(48)).decode()
    occupied = set()
    for name, default in PORTS.items():
        offsets = (0, 1000) if name == "NACOS" else (0,)
        host = env["SMARTLECT_SEATA_IP"] if name == "SEATA" else "127.0.0.1"
        port = free_ports(default, offsets, occupied, host)
        env[f"SMARTLECT_{name}_PORT"] = str(port)
        occupied.update(port + offset for offset in offsets)
    env["SMARTLECT_NACOS_GRPC_PORT"] = str(int(env["SMARTLECT_NACOS_PORT"]) + 1000)
    env["SMARTLECT_NACOS_ADDR"] = "127.0.0.1:" + env["SMARTLECT_NACOS_PORT"]
    env["SMARTLECT_GROWTH_BASE_URL"] = "http://127.0.0.1:" + env["SMARTLECT_GROWTH_PORT"]
    env["SMARTLECT_ALLOWED_ORIGINS"] = ','.join('http://127.0.0.1:' + env[k] for k in ('SMARTLECT_GATEWAY_PORT', 'SMARTLECT_WEB_USER_PORT', 'SMARTLECT_WEB_ADMIN_PORT'))
    with ENV_FILE.open("x") as target:
        os.chmod(ENV_FILE, 0o600)
        target.write("\n".join(f"{k}={v}" for k, v in env.items()) + "\n")
    print("Created independent credentials and available ports in run/runtime.env (mode 600).")


def compose(*args, capture=False):
    return run("docker", "compose", "--project-name", "smartlect", "--env-file",
               str(ENV_FILE), "-f", str(ROOT / "deploy/compose.yaml"), *args, capture=capture)


def verify_project():
    ids = run("docker", "ps", "-aq", "--filter", "label=com.docker.compose.project=smartlect", capture=True).split()
    if ids:
        for container in json.loads(run("docker", "inspect", *ids, capture=True)):
            labels = container["Config"]["Labels"]
            if labels.get("com.docker.compose.project.config_files") != str(ROOT / "deploy/compose.yaml"):
                raise RuntimeError("Existing smartlect container belongs to another checkout; refusing to modify it")


def nacos_request(env, path, data):
    req = urllib.request.Request("http://" + env["SMARTLECT_NACOS_ADDR"] + path,
                                 data=urllib.parse.urlencode(data).encode())
    with urllib.request.urlopen(req, timeout=10) as response:
        return json.load(response)


def infra_up(env):
    verify_project()
    compose("up", "-d", "--wait", "--wait-timeout", "240", "mysql", "redis", "rabbitmq", "nacos")
    try:
        nacos_request(env, "/nacos/v1/auth/users/admin", {"password": env["SMARTLECT_NACOS_PASSWORD"]})
    except urllib.error.HTTPError as error:
        if error.code not in (400, 409):
            raise
    result = nacos_request(env, "/nacos/v1/auth/login",
                           {"username": env["SMARTLECT_NACOS_USERNAME"], "password": env["SMARTLECT_NACOS_PASSWORD"]})
    if not result.get("accessToken"):
        raise RuntimeError("Smartlect Nacos login failed")
    compose("up", "-d", "--build", "--wait", "--wait-timeout", "180", "seata")
    print("Smartlect middleware is healthy; commerce/growth application readiness is a separate gate.")


def infra_check(env):
    verify_project()
    states = compose("ps", "--all", "--format", "{{.Service}} {{.Health}} {{.State}}", capture=True)
    healthy = {line.split()[0] for line in states.splitlines() if line.endswith("healthy running")}
    if not {"mysql", "redis", "rabbitmq", "nacos", "seata"} <= healthy:
        raise RuntimeError("Middleware health check incomplete; run infra-up first")
    token = nacos_request(env, "/nacos/v1/auth/login", {
        "username": env["SMARTLECT_NACOS_USERNAME"], "password": env["SMARTLECT_NACOS_PASSWORD"]})["accessToken"]
    query = urllib.parse.urlencode({"accessToken": token, "serviceName": "smartlect-seata",
                                   "groupName": "SMARTLECT_SEATA_GROUP", "healthyOnly": "true"})
    with urllib.request.urlopen("http://" + env["SMARTLECT_NACOS_ADDR"] +
                                "/nacos/v1/ns/instance/list?" + query, timeout=10) as response:
        hosts = json.load(response)["hosts"]
    if not any(host["healthy"] and host["ip"] == env["SMARTLECT_SEATA_IP"]
               and host["port"] == int(env["SMARTLECT_SEATA_PORT"]) for host in hosts):
        raise RuntimeError("Seata registration missing")
    sql = ("SELECT GRANTEE,TABLE_SCHEMA,PRIVILEGE_TYPE FROM information_schema.SCHEMA_PRIVILEGES "
           "UNION SELECT GRANTEE,'*',PRIVILEGE_TYPE FROM information_schema.USER_PRIVILEGES "
           "WHERE PRIVILEGE_TYPE <> 'USAGE';")
    rows = compose("exec", "-T", "mysql", "sh", "-ec",
                   'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -N -uroot -e "$1"', "infra-check", sql, capture=True)
    privileges = [row.split("\t") for row in rows.splitlines()]
    for user, expected in (("smartlect_growth", {"smartlect_growth"}),
                           ("smartlect_app", {"smartlect_" + domain for domain in DATABASES}),
                           ("smartlect_flyway", {"smartlect_" + domain for domain in DATABASES})):
        grants = [row for row in privileges if row[0] == f"'{user}'@'%'"]
        if {row[1] for row in grants} != expected:
            raise RuntimeError(f"Unexpected schemas granted to {user}")
        if user == "smartlect_app":
            if {row[2] for row in grants} != {"SELECT", "INSERT", "UPDATE", "DELETE"}:
                raise RuntimeError("Unexpected commercial application privileges")
    print("Infrastructure checks passed: authenticated Nacos, healthy Seata registration, isolated growth/Flyway/app grants.")


def process_identity(pid):
    proc = Path("/proc") / str(pid)
    for _ in range(100):
        try:
            fields = (proc / "stat").read_text().rsplit(")", 1)[1].split()
            if fields[0] == "Z":
                return None
            cmdline = (proc / "cmdline").read_bytes().rstrip(b"\0")
            executable, cwd = os.readlink(proc / "exe"), os.readlink(proc / "cwd")
            after = (proc / "stat").read_text().rsplit(")", 1)[1].split()
            if after[0] == "Z":
                return None
            if cmdline and fields[19] == after[19] and executable == os.readlink(proc / "exe"):
                return {"pid": pid, "start_ticks": fields[19], "exe": executable,
                        "cwd": cwd, "cmdline": cmdline.decode().split("\0")}
        except (FileNotFoundError, ProcessLookupError):
            if not proc.exists():
                return None
        time.sleep(0.01)
    raise RuntimeError(f"PID {pid} has no stable readable identity; refusing to signal it")


def owned_process(record):
    identity = process_identity(record["pid"])
    if identity is None:
        return False
    if any(identity[key] != record[key] for key in identity) or identity["cwd"] != str(ROOT):
        raise RuntimeError(f"PID {record['pid']} identity changed; refusing to signal it")
    return True


def load_processes():
    return json.loads(PROCESS_FILE.read_text()) if PROCESS_FILE.exists() else {}


def save_processes(records):
    temporary = PROCESS_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(records, indent=2) + "\n")
    os.chmod(temporary, 0o600)
    temporary.replace(PROCESS_FILE)


def signal_process(record, signum):
    try:
        pidfd = os.pidfd_open(record["pid"])
    except ProcessLookupError:
        return
    try:
        if owned_process(record):
            signal.pidfd_send_signal(pidfd, signum)
    except ProcessLookupError:
        pass
    finally:
        os.close(pidfd)


def stop_process(record):
    if not owned_process(record):
        return
    signal_process(record, signal.SIGTERM)
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if not owned_process(record):
            return
        time.sleep(0.2)
    if owned_process(record):
        signal_process(record, signal.SIGKILL)


def apps_down():
    records = load_processes()
    for service in reversed(APPS):
        if service in records:
            stop_process(records[service])
            del records[service]
            save_processes(records)
            print(f"Stopped Smartlect {service}.", flush=True)


def app_health(service, record):
    if not owned_process(record):
        return False
    path = '/admin/' if service == 'web-admin' else '/' if service == 'web-user' else "/health" if service == "growth" else "/actuator/health"
    try:
        if service == "growth-worker":
            health = json.loads((ROOT / "run/worker-status.json").read_text())
            return health.get("pid") == record["pid"] and health.get("connected") and 0 <= time.time() - health["observed_at"] < 5
        with urllib.request.urlopen(f"http://127.0.0.1:{record['port']}{path}", timeout=2) as response:
            if service in {'web-user', 'web-admin'}:
                return response.status == 200 and b'Smartlect' in response.read(8192)
            health = json.load(response)
        return health.get("status") in ("UP", "ok")
    except (OSError, ValueError, KeyError):
        return False


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def package_fingerprint(directory):
    files = sorted(path for path in directory.rglob("*") if path.is_file()
                   and "__pycache__" not in path.parts and path.suffix != ".pyc")
    if not files:
        raise RuntimeError(f"Installed Python package contains no source files: {directory}")
    manifest = "\n".join(f"{path.relative_to(directory)}:{file_sha256(path)}" for path in files)
    return hashlib.sha256(manifest.encode()).hexdigest(), max(path.stat().st_mtime_ns for path in files)


def immutable_jar(source, directory):
    # ponytail: retain old hashes; prune only inactive snapshots if disk usage matters.
    before = source.stat()
    directory.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=directory, suffix=".tmp")
    os.close(descriptor)
    temporary = Path(name)
    try:
        shutil.copyfile(source, temporary)
        after = source.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
            raise RuntimeError(f"JAR changed while copying: {source}; wait for build completion")
        try:
            with zipfile.ZipFile(temporary) as archive:
                if archive.testzip() or not any(name.startswith("BOOT-INF/classes/") for name in archive.namelist()):
                    raise RuntimeError(f"Incomplete executable JAR: {source}; wait for build completion")
        except zipfile.BadZipFile as error:
            raise RuntimeError(f"Invalid JAR: {source}; wait for build completion") from error
        digest = file_sha256(temporary)
        target = directory / f"{digest}.jar"
        if target.exists():
            if file_sha256(target) != digest:
                raise RuntimeError(f"Immutable runtime JAR checksum changed: {target}")
        else:
            temporary.chmod(0o444)
            os.link(temporary, target)
        return target, digest, after.st_mtime_ns
    finally:
        temporary.unlink(missing_ok=True)


def start_app(service, env, records):
    if service in {"growth", "growth-worker"}:
        env = {**env, **model_env()}
        executable = ROOT / "growth/.venv/bin/python"
        command = [str(executable), "-I", "-m", "smartlect.worker" if service == "growth-worker" else "smartlect.app"]
        artifact = Path(run(str(executable), "-I", "-c",
                            "import importlib.util; print(next(iter(importlib.util.find_spec('smartlect').submodule_search_locations)))",
                            capture=True).strip())
        source_sha, stamp = package_fingerprint(artifact)
    elif service in {'web-user', 'web-admin'}:
        frontend = ROOT / 'web' / service.removeprefix('web-')
        config = frontend / ('vite.config.ts' if service == 'web-user' else 'vite.config.js')
        artifact = frontend / 'dist'
        source_sha, stamp = package_fingerprint(artifact)
        source_sha = hashlib.sha256((source_sha + file_sha256(config)
                                    + file_sha256(frontend / 'package-lock.json')).encode()).hexdigest()
        executable = Path(shutil.which('node') or '/missing-node')
        command = [str(executable), str(frontend / 'node_modules/vite/bin/vite.js'), 'preview',
                   str(frontend), '--config', str(config)]
    else:
        module = ROOT / "backend" / f"smartlect-{service}"
        target = module / ("target" if service in ("admin", "gateway") else "app/target")
        artifacts = list(target.glob(f"smartlect-{service}-*.jar"))
        if len(artifacts) != 1:
            raise RuntimeError(f"Expected one executable JAR for {service}; run build first")
        artifact = artifacts[0]
        runtime_jar, source_sha, stamp = immutable_jar(artifact, ROOT / "run/apps" / service)
        executable = Path(shutil.which("java") or "/missing-java")
        command = [str(executable), "-Xms64m", "-Xmx" + env.get("SMARTLECT_JAVA_XMX", "256m"),
                   "-XX:MaxMetaspaceSize=192m", "-XX:MaxDirectMemorySize=64m", "-XX:ActiveProcessorCount=2",
                   f"-Dcsp.sentinel.log.dir={ROOT}/run/logs/sentinel/{service}",
                   f"-DJM.LOG.PATH={ROOT}/run/logs/{service}",
                   f"-DJM.SNAPSHOT.PATH={ROOT}/run/cache/{service}",
                   "-jar", str(runtime_jar), "--server.address=127.0.0.1", "--spring.cloud.nacos.discovery.ip=127.0.0.1"]
        # OTel javaagent 只能经命令行注入（JAVA_TOOL_OPTIONS 已剥离）；agent 文件
        # 不存在时（本地无追踪）完全不影响原命令。约束 #7：改本函数后
        # check_independence + 进程身份核验必须仍过。
        agent = env.get("SMARTLECT_OTEL_AGENT") or str(ROOT / "run" / "opentelemetry-javaagent.jar")
        if not Path(agent).is_file():
            agent = "/opt/otel/opentelemetry-javaagent.jar"
        if Path(agent).is_file():
            endpoint = env.get("SMARTLECT_OTEL_EXPORTER", "http://127.0.0.1:4318")
            command[1:1] = [f"-javaagent:{agent}",
                            f"-Dotel.service.name=smartlect-{service}",
                            f"-Dotel.exporter.otlp.endpoint={endpoint}",
                            "-Dotel.exporter.otlp.protocol=http/protobuf"]
    if not executable.exists():
        raise RuntimeError(f"Missing runtime executable for {service}; run build first")
    env_stamp = hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest()
    if service in records and owned_process(records[service]):
        if (records[service].get("source_sha256") == source_sha and records[service].get("env_stamp") == env_stamp
                and records[service]["cmdline"] == command):
            return
        stop_process(records[service])
    port = None if service == "growth-worker" else int(env[f"SMARTLECT_{service.upper().replace('-', '_')}_PORT"])
    if port is not None:
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
    launch_env = {**os.environ, **env}
    for variable in ("JAVA_TOOL_OPTIONS", "JDK_JAVA_OPTIONS", "CLASSPATH", "PYTHONPATH"):
        launch_env.pop(variable, None)
    launch_env["SMARTLECT_PROJECT_FOLDER"] = str(ROOT / "run/uploads") + "/"
    launch_env["SMARTLECT_WORKER_STATUS_FILE"] = str(ROOT / "run/worker-status.json")
    launch_env['LANGSMITH_TRACING'] = 'false'
    launch_env['LANGCHAIN_TRACING_V2'] = 'false'
    if service in {'web-user', 'web-admin'}:
        launch_env = {k: v for k, v in os.environ.items() if k in {'PATH', 'LANG', 'LC_ALL', 'TZ'}}
        launch_env['SMARTLECT_' + service.upper().replace('-', '_') + '_PORT'] = str(port)
        launch_env['SMARTLECT_GATEWAY_URL'] = 'http://127.0.0.1:' + env['SMARTLECT_GATEWAY_PORT']
    logs = ROOT / "run/logs"
    logs.mkdir(parents=True, exist_ok=True)
    with (logs / f"smartlect-{service}.log").open("a") as output:
        output.write(f"\nSmartlect {service} startup at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        output.flush()
        process = subprocess.Popen(command, cwd=ROOT, env=launch_env, stdin=subprocess.DEVNULL,
                                   stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
    identity = process_identity(process.pid)
    if identity is None:
        raise RuntimeError(f"{service} exited during launch; inspect run/logs/smartlect-{service}.log")
    if identity["cmdline"] != command or identity["exe"] != str(executable.resolve()) or identity["cwd"] != str(ROOT):
        raise RuntimeError(f"{service} PID {process.pid} does not match the exact launched command")
    records[service] = {**identity, "port": port, "artifact_stamp": stamp, "source_sha256": source_sha,
                        "source_artifact": str(artifact), "env_stamp": env_stamp}
    save_processes(records)
    print(f"Started Smartlect {service}: PID {process.pid}, port {port}.", flush=True)


def wait_apps(services, records):
    pending = set(services)
    deadline = time.monotonic() + 240
    while pending and time.monotonic() < deadline:
        for service in tuple(pending):
            if not owned_process(records[service]):
                raise RuntimeError(f"{service} exited; inspect run/logs/smartlect-{service}.log")
            if app_health(service, records[service]):
                pending.remove(service)
                print(f"Smartlect {service} health passed.", flush=True)
        if pending:
            time.sleep(1)
    if pending:
        raise RuntimeError(f"Health timeout: {', '.join(sorted(pending))}; inspect run/logs/")


def install_catalog(env):
    import importlib.util
    spec = importlib.util.spec_from_file_location("install_catalog", ROOT / "scripts/install_catalog.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.apply_catalog(env)


def apps_up(env):
    infra_check(env)
    compose("exec", "-T", "mysql", "sh", "-ec",
            'MYSQL_PWD="$SMARTLECT_FLYWAY_PASSWORD" mysql -usmartlect_flyway -e "$1"',
            "seata-schema", (ROOT / "deploy/sql/16-seata-undo.sql").read_text())
    records = load_processes()
    for services in (('growth-worker',), APPS[1:9], ('admin', 'gateway'), ('web-user', 'web-admin')):
        for service in services:
            start_app(service, env, records)
            # Warm one JVM at a time on the shared WSL host.
            wait_apps((service,), records)
            if service == "stock":
                install_catalog(env)
    apps_check(env)
    print("Smartlect application startup smoke passed: nine Java services, AI API, Growth worker and both UI health.")


def apps_check(env):
    records = load_processes()
    if any(service not in records for service in APPS):
        raise RuntimeError("Some application processes are not registered; run up first")
    wait_apps(APPS, records)
    token = nacos_request(env, "/nacos/v1/auth/login", {
        "username": env["SMARTLECT_NACOS_USERNAME"], "password": env["SMARTLECT_NACOS_PASSWORD"]})["accessToken"]
    pending = set(APPS) - {"growth", "growth-worker", "web-user", "web-admin"}
    deadline = time.monotonic() + 30
    while pending and time.monotonic() < deadline:
        for service in tuple(pending):
            query = urllib.parse.urlencode({"accessToken": token, "serviceName": f"smartlect-{service}",
                                           "groupName": env["SMARTLECT_NACOS_GROUP"], "healthyOnly": "true"})
            with urllib.request.urlopen("http://" + env["SMARTLECT_NACOS_ADDR"] +
                                        "/nacos/v1/ns/instance/list?" + query, timeout=5) as response:
                hosts = json.load(response)["hosts"]
            if any(host["healthy"] and host["ip"] == "127.0.0.1"
                   and host["port"] == records[service]["port"] for host in hosts):
                pending.remove(service)
        if pending:
            time.sleep(1)
    if pending:
        raise RuntimeError(f"Missing application discovery registrations: {', '.join(sorted(pending))}")
    schemas = compose("exec", "-T", "mysql", "sh", "-ec",
                      'MYSQL_PWD="$SMARTLECT_FLYWAY_PASSWORD" mysql -N -usmartlect_flyway -e "$1"',
                      "seata-check", "SELECT table_schema FROM information_schema.tables WHERE table_name='undo_log';",
                      capture=True).splitlines()
    if set(schemas) != {"smartlect_" + domain for domain in DATABASES}:
        raise RuntimeError("Seata undo_log metadata is missing from a business schema")
    print("Application checks passed: thirteen owned healthy processes, nine Nacos registrations, eight Seata undo tables.")


def apps_status():
    records = load_processes()
    for service in APPS:
        record = records.get(service)
        state = "stopped" if record is None or not owned_process(record) else (
            "healthy" if app_health(service, record) else "starting/unhealthy")
        print(f"smartlect-{service}: {state}" + (f" (PID {record['pid']}, port {record['port']})" if record else ""))


def self_test():
    with socket.socket() as blocker:
        blocker.bind(("127.0.0.1", 0))
        busy = blocker.getsockname()[1]
        assert free_ports(busy) != busy
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "runtime.env"
        path.write_text("# local\nSMARTLECT_TOKEN=abc==\nSMARTLECT_EMPTY=\n")
        assert parse_env(path) == {"SMARTLECT_TOKEN": "abc==", "SMARTLECT_EMPTY": ""}
        provider = Path(temp) / "model.env"
        provider.write_text("SMARTLECT_MODEL_API_KEY=literal-$(false)\nSMARTLECT_MODEL_ID=qwen3.7-plus\n")
        provider.chmod(0o600)
        assert model_env(provider)["SMARTLECT_MODEL_API_KEY"] == "literal-$(false)"
        provider.write_text("SMARTLECT_INTERNAL_TOKEN=forbidden\n")
        try:
            model_env(provider)
            raise AssertionError("Model config overwrote business credentials")
        except RuntimeError:
            pass
        from unittest.mock import patch
        path.chmod(0o600)
        with patch.dict(globals(), ENV_FILE=path), patch.object(sys, 'argv', ['runtime.py', 'model-mode', 'mock']):
            main()
        assert parse_env(path)['SMARTLECT_MODEL_MODE'] == 'mock'
        assert parse_env(path)['SMARTLECT_TOKEN'] == 'abc==' and path.stat().st_mode & 0o777 == 0o600
        with patch.dict(globals(), ENV_FILE=path), patch.object(sys, 'argv', ['runtime.py', 'model-mode', 'unsafe']):
            try:
                main()
                raise AssertionError('Invalid mode accepted')
            except RuntimeError:
                pass
        provider.write_text("SMARTLECT_MODEL_ID=qwen3.7-plus\n")
        provider.chmod(0o644)
        try:
            model_env(provider)
            raise AssertionError("World-readable credentials accepted")
        except RuntimeError:
            pass
        jar = Path(temp) / "source.jar"
        with zipfile.ZipFile(jar, "w") as archive:
            archive.writestr("BOOT-INF/classes/test.class", b"original")
        snapshot, digest, _ = immutable_jar(jar, Path(temp) / "runtime")
        assert immutable_jar(jar, snapshot.parent)[0] == snapshot
        with zipfile.ZipFile(jar, "w") as archive:
            archive.writestr("BOOT-INF/classes/test.class", b"rebuilt")
        replacement, _, _ = immutable_jar(jar, snapshot.parent)
        assert replacement != snapshot and file_sha256(snapshot) == digest
        assert snapshot.stat().st_mode & 0o222 == 0
        jar.write_bytes(b"unfinished build")
        try:
            immutable_jar(jar, snapshot.parent)
            raise AssertionError("Invalid JAR accepted")
        except RuntimeError:
            assert file_sha256(snapshot) == digest
        package = Path(temp) / "package"
        (package / "ads").mkdir(parents=True)
        (package / "app.py").write_text("pass\n")
        settings = package / "ads/config.py"
        settings.write_text("VALUE = 1\n")
        package_sha, _ = package_fingerprint(package)
        timestamp = settings.stat().st_mtime_ns
        settings.write_text("VALUE = 2\n")
        os.utime(settings, ns=(timestamp, timestamp))
        assert package_fingerprint(package)[0] != package_sha
        sql = package / "migration.sql"
        sql.write_text("SELECT 1;\n")
        with_sql, _ = package_fingerprint(package)
        sql.write_text("SELECT 2;\n")
        assert package_fingerprint(package)[0] != with_sql
    test_env = {**os.environ, **{f"SMARTLECT_{key}": "a" * 48 for key in
                ("MYSQL_PASSWORD", "FLYWAY_PASSWORD", "NACOS_MYSQL_PASSWORD",
                 "SEATA_MYSQL_PASSWORD", "GROWTH_MYSQL_PASSWORD")}}
    script = 'docker_process_sql() { cat; }; source "$1"'
    args = ["bash", "-ec", script, "self-test", str(ROOT / "deploy/mysql-init.sh")]
    sql = subprocess.run(args, env=test_env, check=True, text=True, capture_output=True).stdout
    assert sql.count("CREATE DATABASE smartlect_") == 11
    grants = [line for line in sql.splitlines() if "TO 'smartlect_growth'" in line]
    assert grants == ["GRANT ALL ON smartlect_growth.* TO 'smartlect_growth'@'%';"]
    test_env["SMARTLECT_MYSQL_PASSWORD"] = "invalid'password"
    assert subprocess.run(args, env=test_env, text=True, capture_output=True).returncode != 0
    child_command = [sys.executable, "-c", "import time; time.sleep(30)"]
    child = subprocess.Popen(child_command, cwd=ROOT)
    try:
        from unittest.mock import patch
        original_read = Path.read_bytes
        empty_reads = []

        def cold_cmdline(path):
            if path == Path(f"/proc/{child.pid}/cmdline") and not empty_reads:
                empty_reads.append(True)
                return b""
            return original_read(path)

        with patch.object(Path, "read_bytes", cold_cmdline):
            identity = process_identity(child.pid)
        assert empty_reads and identity["cmdline"] == child_command
        assert owned_process(identity)
        try:
            signal_process({**identity, "start_ticks": "wrong"}, signal.SIGTERM)
            raise AssertionError("Tampered PID identity was accepted")
        except RuntimeError:
            assert child.poll() is None
        stop_process(identity)
        assert child.wait(timeout=2) == -signal.SIGTERM
    finally:
        if child.poll() is None:
            child.terminate()
            child.wait(timeout=2)
    print("Runtime checks passed: immutable JARs, full Python package hashes, ports, env, grants, credentials, process signaling.")
    calls = []
    with patch.dict(globals(), infra_check=lambda env: None, compose=lambda *a, **kw: None,
                    load_processes=lambda: {}, apps_check=lambda env: None,
                    install_catalog=lambda env: calls.append(('catalog',)),
                    start_app=lambda name, env, records: calls.append(('start', name)),
                    wait_apps=lambda names, records: calls.append(('healthy', tuple(names)))):
        apps_up({})
    assert calls[:2] == [('start', 'growth-worker'), ('healthy', ('growth-worker',))]
    assert ('catalog',) in calls and calls.index(('catalog',)) > calls.index(('healthy', ('stock',)))
    print('Consumer health precedes every Java producer startup.')


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    if command == "bootstrap":
        bootstrap()
        return
    if command == "self-test":
        self_test()
        return
    if not ENV_FILE.exists():
        raise RuntimeError("Run ./scripts/dev.sh bootstrap first")
    env = parse_env(ENV_FILE)
    if command == "config":
        compose("config", "--quiet")
        print(json.dumps({k: v for k, v in env.items() if k.endswith("_PORT")}, indent=2))
    elif command == "model-mode":
        mode = sys.argv[2] if len(sys.argv) == 3 else ''
        if mode not in {'live', 'mock', 'rule-fallback'}:
            raise RuntimeError('Usage: ./scripts/dev.sh model-mode {live|mock|rule-fallback}')
        if ENV_FILE.is_symlink() or ENV_FILE.stat().st_mode & 0o777 != 0o600:
            raise RuntimeError('run/runtime.env must be a regular mode-600 file')
        if mode == 'live' and not model_env().get('SMARTLECT_MODEL_API_KEY'):
            raise RuntimeError('Configure SMARTLECT_MODEL_API_KEY in run/model.env first')
        env['SMARTLECT_MODEL_MODE'] = mode
        temporary = ENV_FILE.with_suffix('.env.tmp')
        with temporary.open('x') as target:
            os.chmod(temporary, 0o600)
            target.write('\n'.join(f'{key}={value}' for key, value in env.items()) + '\n')
        temporary.replace(ENV_FILE)
        print(f'Model mode saved: {mode}. Run ./scripts/dev.sh up to apply it.')
    elif command == "status":
        verify_project()
        compose("ps", "--all")
        apps_status()
    elif command == "infra-up":
        infra_up(env)
    elif command == "infra-check":
        infra_check(env)
    elif command == "catalog":
        install_catalog(env)
    elif command == "up":
        apps_up(env)
    elif command == "apps-check":
        apps_check(env)
    elif command == "apps-down":
        apps_down()
    elif command == "down":
        verify_project()
        apps_down()
        compose("down", "--timeout", "30")
    else:
        raise RuntimeError(f"Unknown runtime command: {command}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, subprocess.CalledProcessError, urllib.error.URLError) as error:
        print(f"Smartlect runtime failed: {error}", file=sys.stderr)
        sys.exit(1)
