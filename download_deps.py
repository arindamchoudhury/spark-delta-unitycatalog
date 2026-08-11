#!/usr/bin/env python3
"""Download Spark/Hadoop tarballs and Maven jars declared in spark/Dockerfile.

Requires: pip install httpx[http2]

Run from anywhere:
    python3 download_deps.py              # from project root
    python  download_deps.py             # Windows
"""

import asyncio
import re
import sys
import threading
from pathlib import Path

try:
    import httpx
except ImportError:
    sys.exit("Missing dependency: pip install httpx[http2]")

ROOT_DIR   = Path(__file__).parent
DOCKERFILE = ROOT_DIR / "spark" / "Dockerfile"
TAR_DIR    = ROOT_DIR / "spark" / "tar"
JAR_DIR    = ROOT_DIR / "spark" / "jar"

# closer.lua redirects to the nearest Apache mirror — same speed boost a browser gets
APACHE_MIRROR = "https://www.apache.org/dyn/closer.lua"
MAVEN         = "https://repo1.maven.org/maven2"

CHUNK = 8 * 1024 * 1024  # 8 MB read buffer

_lock    = threading.Lock()
_counter = 0
_total   = 0


def _log(msg: str) -> None:
    with _lock:
        print(msg, flush=True)


def _done(name: str) -> None:
    global _counter
    with _lock:
        _counter += 1
        print(f"  [{_counter}/{_total}] done  {name}", flush=True)


def parse_env(path: Path) -> dict[str, str]:
    text = re.sub(r"\\\n[ \t]*", " ", path.read_text())
    env: dict[str, str] = {}
    for block in re.finditer(r"^ENV\s+(.+?)$", text, re.MULTILINE):
        for m in re.finditer(r"([A-Z][A-Z0-9_]+)=(\S+)", block.group(1)):
            env[m.group(1)] = m.group(2)
    return env


async def fetch(client: httpx.AsyncClient, url: str, dest: Path) -> None:
    if dest.exists():
        _done(f"{dest.name} (cached)")
        return
    _log(f"  fetch {dest.name} ...")
    try:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            total     = int(resp.headers.get("content-length", 0))
            last_mark = -1
            with dest.open("wb") as f:
                async for chunk in resp.aiter_bytes(CHUNK):
                    f.write(chunk)
                    downloaded = resp.num_bytes_downloaded
                    if total > 0:
                        pct  = min(int(downloaded / total * 100), 100)
                        mark = pct // 10
                        if mark > last_mark:
                            last_mark = mark
                            _log(f"  {dest.name}  {pct}%")
                    else:
                        mb = downloaded // (1024 * 1024)
                        if mb > last_mark:
                            last_mark = mb
                            _log(f"  {dest.name}  {mb} MB")
    except httpx.HTTPError as exc:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"{dest.name}: {exc}") from exc
    _done(dest.name)


def apache_url(path: str) -> str:
    return f"{APACHE_MIRROR}/{path}?action=download"


def jar_url(group: str, artifact: str, version: str) -> str:
    g = group.replace(".", "/")
    return f"{MAVEN}/{g}/{artifact}/{version}/{artifact}-{version}.jar"


async def main() -> None:
    global _total

    TAR_DIR.mkdir(parents=True, exist_ok=True)
    JAR_DIR.mkdir(parents=True, exist_ok=True)

    env = parse_env(DOCKERFILE)

    spark_ver  = env["SPARK_VERSION"]
    spark_pkg  = env["SPARK_PACKAGE"]
    hadoop_ver = env["HADOOP_VERSION"]
    scala      = env["SCALA_VERSION"]
    hadoop_aws = env["HADOOP_AWS_VERSION"]
    aws_sdk    = env["AWS_SDK_BUNDLE_VERSION"]
    accel      = env["AWS_ANALYTICS_ACCELERATOR_VERSION"]
    wildfly    = env["WILDFLY_OPENSSL_VERSION"]
    uc_ver     = env["UNITYCATALOG_VERSION"]
    uc_spark   = env["UNITYCATALOG_SPARK_PROFILE"]
    delta_ver  = env["DELTA_VERSION"]

    downloads = [
        (apache_url(f"spark/spark-{spark_ver}/{spark_pkg}.tgz"),                                        TAR_DIR / f"{spark_pkg}.tgz"),
        (apache_url(f"hadoop/common/hadoop-{hadoop_ver}/hadoop-{hadoop_ver}.tar.gz"),                   TAR_DIR / f"hadoop-{hadoop_ver}.tar.gz"),
        (jar_url("org.apache.hadoop",                       "hadoop-aws",                  hadoop_aws), JAR_DIR / f"hadoop-aws-{hadoop_aws}.jar"),
        (jar_url("software.amazon.awssdk",                  "bundle",                      aws_sdk),    JAR_DIR / f"bundle-{aws_sdk}.jar"),
        (jar_url("software.amazon.s3.analyticsaccelerator", "analyticsaccelerator-s3",     accel),      JAR_DIR / f"analyticsaccelerator-s3-{accel}.jar"),
        (jar_url("org.wildfly.openssl",                     "wildfly-openssl",             wildfly),    JAR_DIR / f"wildfly-openssl-{wildfly}.jar"),
        (jar_url("io.unitycatalog",                         "unitycatalog-client",         uc_ver),     JAR_DIR / f"unitycatalog-client-{uc_ver}.jar"),
        (jar_url("io.unitycatalog",                         "unitycatalog-hadoop",         uc_ver),     JAR_DIR / f"unitycatalog-hadoop-{uc_ver}.jar"),
        # Since UC 0.5.x the Spark connector ships one artifact per Spark minor
        # (unitycatalog-spark_<spark>_<scala>), not a single unitycatalog-spark_<scala>.
        (jar_url("io.unitycatalog",             f"unitycatalog-spark_{uc_spark}_{scala}",  uc_ver),     JAR_DIR / f"unitycatalog-spark_{uc_spark}_{scala}-{uc_ver}.jar"),
        (jar_url("io.delta",                                f"delta-spark_{scala}",        delta_ver),  JAR_DIR / f"delta-spark_{scala}-{delta_ver}.jar"),
        (jar_url("io.delta",                                "delta-storage",               delta_ver),  JAR_DIR / f"delta-storage-{delta_ver}.jar"),
    ]

    _total = len(downloads)

    async with httpx.AsyncClient(http2=True, follow_redirects=True, timeout=300) as client:
        results = await asyncio.gather(
            *[fetch(client, url, dest) for url, dest in downloads],
            return_exceptions=True,
        )

    errors = [str(r) for r in results if isinstance(r, Exception)]
    if errors:
        sys.exit("FAILED:\n" + "\n".join(f"  {e}" for e in errors))

    print("\ndone.")


if __name__ == "__main__":
    # ProactorEventLoop (Windows default) doesn't handle Ctrl+C; SelectorEventLoop does.
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    try:
        asyncio.run(main(), loop_factory=loop_factory)
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)
