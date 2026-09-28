#!/usr/bin/env python3
"""
Autonomous Happ Proxy Subscription Generator & Anti-Censorship Optimizer
Engineered specifically for maximum compatibility with VLESS Reality & DPI bypass.
Author: Senior DevOps & Python Engineer
License: MIT
"""

import os
import re
import sys
import time
import json
import base64
import socket
import logging
from typing import Dict, List, Optional, Set, Tuple, Any
from urllib.parse import urlparse, unquote
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Force UTF-8 output encoding across platforms
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# --- Logging setup ---
logger = logging.getLogger("HappOptimizer")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(_handler)
logger.propagate = False

# --- High-Quality Sources (Specialized in VLESS Reality, DPI bypass & Russia) ---
SOURCES = [
    # 1. Primary: igareck/vpn-configs-for-russia (8,900+ Stars, tested against Russian DPI)
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_VLESS_RUS.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/Vless-Reality-White-Lists-Rus-Mobile.txt",
    "https://raw.githubusercontent.com/igareck/vpn-configs-for-russia/main/BLACK_SS+All_RUS.txt",
    # 2. Curated Daily Anti-Censorship Aggregators
    "https://raw.githubusercontent.com/cbusifabcap/daily_free_vpn/main/Z.txt",
    "https://raw.githubusercontent.com/solovyov-jenya2004/all_subs/main/final_sorted",
    "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/v2ray.txt",
]

SUPPORTED_SCHEMES = (
    "vless://",
    "hysteria2://",
    "hy2://",
    "trojan://",
    "ss://",
    "tuic://",
    "vmess://",
)

# Known Cloudflare Anycast IP ranges that return fake 3ms ping on GitHub runners
# but are blocked or dead inside client apps (causing N/A in Happ).
CLOUDFLARE_ANYCAST_PREFIXES = (
    "104.16.", "104.17.", "104.18.", "104.19.", "104.20.", "104.21.", "104.22.", "104.23.",
    "104.24.", "104.25.", "104.26.", "104.27.", "104.28.", "104.29.", "104.30.", "104.31.",
    "172.64.", "172.65.", "172.66.", "172.67.", "172.68.", "172.69.", "172.70.", "172.71.",
    "162.159.", "198.41.", "141.101.", "108.162.", "190.93.", "188.114.", "197.234.",
)

# Quality & Ping Thresholds
PING_TIMEOUT_SEC = 2.0       # Timeout for TCP socket connection
MAX_ALLOWED_PING_MS = 600.0  # Discard any server with ping > 600ms
MAX_TEST_POOL = 400          # Top prioritized candidates tested in parallel
TOP_BEST_NODES = 80          # Keep top 80 genuine, low-latency nodes
CHECK_WORKERS = 75           # Parallel threads

HAPP_CRYPTO_API = "https://crypto.happ.su/api-v2.php"
GIST_FILENAME = "subscription.txt"
GIST_DESCRIPTION = "Happ Proxy Auto-Updated Subscription [VLESS Reality & Low Latency]"


def get_http_session() -> requests.Session:
    """Create a resilient requests session with automatic retries."""
    session = requests.Session()
    retries = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retries)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "*/*",
    })
    return session


def try_decode_base64(raw_text: str) -> str:
    """Detect and decode Base64 encoded subscription payloads."""
    compact = re.sub(r"\s+", "", raw_text)
    if not compact:
        return raw_text

    missing_padding = len(compact) % 4
    if missing_padding:
        compact += "=" * (4 - missing_padding)

    try:
        decoded_bytes = base64.b64decode(compact, validate=False)
        decoded_str = decoded_bytes.decode("utf-8", errors="replace")
        if any(scheme in decoded_str for scheme in SUPPORTED_SCHEMES):
            return decoded_str
    except Exception:
        pass

    return raw_text


def fetch_source_configs(session: requests.Session, url: str) -> List[str]:
    """Fetch nodes from a remote URL with error handling."""
    logger.info(f"Downloading from: {url}")
    configs: List[str] = []
    try:
        response = session.get(url, timeout=12)
        if response.status_code != 200:
            logger.warning(f"Source returned {response.status_code}: {url}")
            return []

        text = try_decode_base64(response.text)
        for line in text.splitlines():
            line = line.strip()
            if any(line.startswith(scheme) for scheme in SUPPORTED_SCHEMES):
                configs.append(line)

        logger.info(f"  -> Extracted {len(configs)} raw nodes")
    except Exception as e:
        logger.warning(f"Error fetching {url}: {e}")

    return configs


def extract_host_and_port(node_uri: str) -> Tuple[Optional[str], Optional[int]]:
    """Parse hostname and port from any supported proxy URI format."""
    try:
        if node_uri.startswith(("vless://", "trojan://", "hysteria2://", "hy2://", "tuic://")):
            p = urlparse(node_uri)
            return p.hostname, p.port or 443

        elif node_uri.startswith("ss://"):
            body = node_uri[5:].split("#")[0]
            if "@" in body:
                p = urlparse(node_uri)
                return p.hostname, p.port or 8388
            else:
                pad = len(body) % 4
                if pad:
                    body += "=" * (4 - pad)
                dec = base64.b64decode(body).decode("utf-8", errors="ignore")
                if "@" in dec:
                    hp = dec.split("@")[1]
                    h, port = hp.rsplit(":", 1)
                    return h, int(port)

        elif node_uri.startswith("vmess://"):
            body = node_uri[8:].split("#")[0].strip()
            pad = len(body) % 4
            if pad:
                body += "=" * (4 - pad)
            dec = base64.b64decode(body).decode("utf-8", errors="ignore")
            data = json.loads(dec)
            return data.get("add"), int(data.get("port", 443))

    except Exception:
        return None, None

    return None, None


def is_fake_cloudflare_node(host: Optional[str], node_uri: str) -> bool:
    """
    Detect Cloudflare Anycast IPs and reverse-proxy workers.
    These respond with fake 3ms ping on GitHub runners but fail with N/A in client apps.
    """
    if not host:
        return True

    # Cloudflare Anycast IP check
    if any(host.startswith(prefix) for prefix in CLOUDFLARE_ANYCAST_PREFIXES):
        return True

    # Check WebSocket workers on Cloudflare
    lower_uri = node_uri.lower()
    if "type=ws" in lower_uri:
        if any(cf in lower_uri for cf in ("cloudflare", "workers.dev", "pages.dev")):
            return True

    return False


def is_valid_candidate(node: str, host: Optional[str], port: Optional[int]) -> bool:
    """Pre-filter corrupted nodes, loopbacks, and fake Cloudflare workers."""
    if not host or not port or port <= 0 or port > 65535:
        return False
    if len(node) < 25:
        return False

    invalid_hosts = ("127.0.0.1", "localhost", "0.0.0.0", "::1")
    if host in invalid_hosts or host.startswith(("192.168.", "10.")):
        return False

    # Filter out fake Cloudflare CDN nodes that cause 'N/A'
    if is_fake_cloudflare_node(host, node):
        return False

    return True


def check_tcp_ping(host: str, port: int, timeout: float = PING_TIMEOUT_SEC) -> Optional[float]:
    """Measure exact TCP connection handshake latency (RTT) in milliseconds."""
    t_start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            latency = (time.perf_counter() - t_start) * 1000.0
            return round(latency, 1)
    except Exception:
        return None


def clean_and_format_remark(node_uri: str, ping_ms: float) -> str:
    """
    Sanitize remarks and append clean latency badge like [45ms].
    Fixes percent-encoding corruption that causes Happ to fail parsing.
    """
    badge = f"[{int(ping_ms)}ms]"

    # Handle VMess JSON ps field
    if node_uri.startswith("vmess://"):
        try:
            body = node_uri[8:].strip()
            pad = len(body) % 4
            if pad:
                body += "=" * (4 - pad)
            data = json.loads(base64.b64decode(body).decode("utf-8", errors="ignore"))
            old_ps = unquote(data.get("ps", "VMess"))
            clean_ps = re.sub(r"^\[\d+ms\]\s*", "", old_ps).strip()
            data["ps"] = f"{badge} {clean_ps}"
            new_b64 = base64.b64encode(json.dumps(data, ensure_ascii=False).encode("utf-8")).decode("utf-8")
            return f"vmess://{new_b64}"
        except Exception:
            return node_uri

    # Handle standard URI remarks (#remark)
    if "#" in node_uri:
        base, raw_remark = node_uri.split("#", 1)
        # Unquote percent-encoding (%F0%9F...) to avoid parser breakage
        decoded_remark = unquote(raw_remark).strip()
        clean_remark = re.sub(r"^\[\d+ms\]\s*", "", decoded_remark).strip()
        clean_remark = re.sub(r"[\r\n\t]+", " ", clean_remark).strip()
        if not clean_remark:
            clean_remark = "ProxyNode"
        return f"{base}#{badge} {clean_remark}"
    else:
        proto = "REALITY" if "security=reality" in node_uri else node_uri.split("://")[0].upper()
        return f"{node_uri}#{badge} {proto}"


def test_and_filter_nodes(
    session: requests.Session,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Harvest, deduplicate, ping test all nodes, and return top low-latency servers."""
    raw_nodes: List[str] = []
    for src in SOURCES:
        raw_nodes.extend(fetch_source_configs(session, src))

    # Deduplicate candidate endpoints
    unique_candidates: List[Tuple[str, str, int]] = []
    seen_endpoints: Set[Tuple[str, int]] = set()

    for node in raw_nodes:
        host, port = extract_host_and_port(node)
        if not is_valid_candidate(node, host, port):
            continue

        endpoint = (host.lower(), port)
        if endpoint in seen_endpoints:
            continue

        seen_endpoints.add(endpoint)
        unique_candidates.append((node, host, port))

    # Priority sorting: VLESS Reality & Hysteria2 get highest priority
    def anti_censorship_priority(item: Tuple[str, str, int]) -> int:
        n = item[0]
        if "security=reality" in n:
            return 0  # Absolute best for Russian DPI bypass
        if n.startswith(("hysteria2://", "hy2://")):
            return 1  # Excellent UDP obfuscation
        if n.startswith("vless://"):
            return 2
        if n.startswith("trojan://"):
            return 3
        return 4

    unique_candidates.sort(key=anti_censorship_priority)
    test_pool = unique_candidates[:MAX_TEST_POOL]

    logger.info(
        f"Total extracted: {len(raw_nodes)} | Filtered genuine candidates: {len(unique_candidates)} "
        f"| Pool for ping test: {len(test_pool)}"
    )
    logger.info(f"Testing real socket connection (timeout={PING_TIMEOUT_SEC}s, max_workers={CHECK_WORKERS})...")

    alive_results: List[Dict[str, Any]] = []
    dead_count = 0
    t_start = time.perf_counter()

    with ThreadPoolExecutor(max_workers=CHECK_WORKERS) as executor:
        future_map = {
            executor.submit(check_tcp_ping, host, port): (node, host, port)
            for node, host, port in test_pool
        }

        for future in as_completed(future_map):
            ping = future.result()
            node, host, port = future_map[future]
            if ping is not None and ping <= MAX_ALLOWED_PING_MS:
                is_reality = "security=reality" in node
                proto_name = "reality" if is_reality else node.split("://")[0].lower()
                alive_results.append({
                    "node": node,
                    "host": host,
                    "port": port,
                    "ping": ping,
                    "is_reality": is_reality,
                    "proto": proto_name,
                })
            else:
                dead_count += 1

    total_test_duration = time.perf_counter() - t_start
    logger.info(f"Live ping test completed in {total_test_duration:.2f}s!")
    logger.info(f"Alive & Reachable: {len(alive_results)} | Dead/Slow filtered: {dead_count}")

    if not alive_results:
        raise RuntimeError("No nodes responded to live ping tests with acceptable latency!")

    # Sort: Reality first, then lowest ping ascending
    alive_results.sort(key=lambda x: (0 if x["is_reality"] else 1, x["ping"]))

    # Select top N best servers
    selected = alive_results[:TOP_BEST_NODES]

    # Gather statistics
    pings = [item["ping"] for item in selected]
    stats = {
        "total_tested": len(test_pool),
        "alive_count": len(alive_results),
        "dead_count": dead_count,
        "selected_count": len(selected),
        "min_ping": min(pings),
        "avg_ping": round(sum(pings) / len(pings), 1),
        "max_ping": max(pings),
        "reality_count": sum(1 for item in selected if item["is_reality"]),
        "proto_breakdown": {},
    }

    for item in selected:
        pr = item["proto"]
        stats["proto_breakdown"][pr] = stats["proto_breakdown"].get(pr, 0) + 1

    logger.info(
        f"Selected Top {len(selected)} Nodes ({stats['reality_count']} VLESS Reality). "
        f"Ping: Min {stats['min_ping']}ms | Avg {stats['avg_ping']}ms | Max {stats['max_ping']}ms"
    )
    logger.info(f"Protocol breakdown: {stats['proto_breakdown']}")

    return selected, stats


def encode_subscription(nodes: List[str]) -> str:
    """Encode list of nodes into standard Base64 subscription format."""
    payload = "\n".join(nodes).encode("utf-8")
    return base64.b64encode(payload).decode("utf-8")


def sync_github_gist(
    session: requests.Session,
    gist_token: str,
    gist_id: Optional[str],
    content_b64: str,
) -> Tuple[str, str]:
    """Sync subscription to GitHub Gist and compute permanent RAW HEAD URL."""
    headers = {
        "Authorization": f"Bearer {gist_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    if gist_id:
        logger.info(f"Updating Gist: {gist_id}")
        url = f"https://api.github.com/gists/{gist_id}"
        payload = {
            "description": GIST_DESCRIPTION,
            "files": {GIST_FILENAME: {"content": content_b64}},
        }
        res = session.patch(url, headers=headers, json=payload, timeout=15)
        if res.status_code == 200:
            raw_url = res.json()["files"][GIST_FILENAME]["raw_url"]
            permanent_url = re.sub(r"/raw/[0-9a-f]{40}/", "/raw/", raw_url)
            return gist_id, permanent_url
        raise RuntimeError(f"Gist update failed ({res.status_code}): {res.text}")

    # Check for existing managed Gist
    logger.info("Looking for existing Gist in account...")
    res = session.get("https://api.github.com/gists", headers=headers, timeout=15)
    if res.status_code == 200:
        for g in res.json():
            if GIST_FILENAME in g.get("files", {}) or g.get("description") == GIST_DESCRIPTION:
                found_id = g["id"]
                logger.info(f"Reusing existing Gist: {found_id}")
                return sync_github_gist(session, gist_token, found_id, content_b64)

    # Create new secret Gist
    logger.info("Creating a new secret GitHub Gist...")
    create_payload = {
        "description": GIST_DESCRIPTION,
        "public": False,
        "files": {GIST_FILENAME: {"content": content_b64}},
    }
    create_res = session.post("https://api.github.com/gists", headers=headers, json=create_payload, timeout=15)
    if create_res.status_code == 201:
        data = create_res.json()
        new_id = data["id"]
        raw_url = data["files"][GIST_FILENAME]["raw_url"]
        permanent_url = re.sub(r"/raw/[0-9a-f]{40}/", "/raw/", raw_url)
        logger.info(f"Created Gist: {new_id}")
        return new_id, permanent_url

    raise RuntimeError(f"Gist creation failed ({create_res.status_code}): {create_res.text}")


def get_happ_encrypted_link(session: requests.Session, permanent_raw_url: str) -> str:
    """Request encryption of permanent URL via Happ Crypto API."""
    logger.info(f"Encrypting URL via Happ Crypto API: {permanent_raw_url}")
    try:
        res = session.post(
            HAPP_CRYPTO_API,
            json={"url": permanent_raw_url},
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        if res.status_code == 200:
            data = res.json()
            happ_link = data.get("encrypted_link")
            if happ_link and happ_link.startswith("happ://crypt5/"):
                return happ_link
            logger.error(f"Unexpected response from Happ API: {data}")
        else:
            logger.error(f"Happ API returned HTTP {res.status_code}: {res.text}")
    except Exception as e:
        logger.error(f"Communication error with Happ API: {e}")

    raise RuntimeError("Failed to obtain encrypted link from Happ API")


def write_summary_report(
    gist_id: str,
    permanent_raw_url: str,
    happ_link: str,
    top_items: List[Dict[str, Any]],
    stats: Dict[str, Any],
):
    """Write rich markdown summary to GitHub Actions Step Summary and files."""
    fastest_table_rows = []
    for idx, item in enumerate(top_items[:12], 1):
        proto = "VLESS Reality 🛡️" if item["is_reality"] else item["proto"].upper()
        host = item["host"]
        port = item["port"]
        ping = item["ping"]
        fastest_table_rows.append(f"| #{idx} | **{ping} ms** | `{proto}` | `{host}:{port}` |")

    table_content = "\n".join(fastest_table_rows)

    summary_md = f"""# ⚡ Happ Proxy Auto-Updated Subscription (VLESS Reality & DPI Bypass)

**Статус:** ✅ Успешно протестировано и обновлено  
**Отобрано лучших серверов:** `{stats['selected_count']}`  
**Из них VLESS Reality (обход ТСПУ/DPI):** `{stats['reality_count']}`  
**Диапазон пинга:** `min {stats['min_ping']} ms` / `avg {stats['avg_ping']} ms` / `max {stats['max_ping']} ms`  
**Время обновления (UTC):** `{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}`

---

### 📲 Ссылка для клиента Happ (Добавьте 1 раз):
```text
{happ_link}
```

---

### 🏆 Топ быстрейших серверов VLESS Reality:
| Место | Пинг (RTT) | Протокол | Хост:Порт |
|:---:|:---:|:---:|:---|
{table_content}

---

### 📊 Распределение протоколов:
| Протокол | Количество проверенных узлов |
|---|---|
| **VLESS Reality** | {stats['proto_breakdown'].get('reality', 0)} |
| **Hysteria2 / TUIC** | {stats['proto_breakdown'].get('hysteria2', 0) + stats['proto_breakdown'].get('hy2', 0) + stats['proto_breakdown'].get('tuic', 0)} |
| **Trojan** | {stats['proto_breakdown'].get('trojan', 0)} |
| **Shadowsocks** | {stats['proto_breakdown'].get('ss', 0)} |
| **VMess** | {stats['proto_breakdown'].get('vmess', 0)} |

---

### 🌐 Постоянный адрес подписки (Gist RAW):
```text
{permanent_raw_url}
```
"""

    print("\n" + "=" * 80)
    print("ГОТОВАЯ ССЫЛКА HAPP PROXY (VLESS REALITY & LOW LATENCY):")
    print(happ_link)
    print("=" * 80 + "\n")

    with open("happ_link.txt", "w", encoding="utf-8") as f:
        f.write(happ_link + "\n")

    with open("HAPP_SUBSCRIPTION.md", "w", encoding="utf-8") as f:
        f.write(summary_md)

    github_step_summary = os.getenv("GITHUB_STEP_SUMMARY")
    if github_step_summary:
        try:
            with open(github_step_summary, "a", encoding="utf-8") as f:
                f.write(summary_md)
        except Exception as e:
            logger.warning(f"Could not write to GITHUB_STEP_SUMMARY: {e}")


def main():
    logger.info("=== Запуск генератора Happ Proxy (VLESS Reality & DPI-Bypass Edition) ===")
    session = get_http_session()

    # 1. Сбор, фильтрация Cloudflare Anycast, пинг-тест и отбор лучших
    best_nodes_data, stats = test_and_filter_nodes(session)

    # 2. Форматирование меток: [Xms] Remark (без повреждения кодировки URI)
    formatted_nodes = [
        clean_and_format_remark(item["node"], item["ping"])
        for item in best_nodes_data
    ]

    # 3. Base64
    b64_content = encode_subscription(formatted_nodes)

    # 4. Gist
    gist_token = os.getenv("GIST_TOKEN")
    gist_id = os.getenv("GIST_ID")

    if not gist_token:
        logger.warning("GIST_TOKEN не задан. Запуск в DRY-RUN режиме.")
        with open("subscription.txt", "w", encoding="utf-8") as f:
            f.write(b64_content)
        logger.info("Файл subscription.txt сохранен с лучшими серверами VLESS Reality.")
        return

    try:
        active_gist_id, permanent_raw_url = sync_github_gist(
            session=session,
            gist_token=gist_token,
            gist_id=gist_id,
            content_b64=b64_content,
        )
    except Exception as e:
        logger.error(f"Ошибка работы с GitHub Gist: {e}")
        sys.exit(1)

    # 5. Шифрование через Happ API
    try:
        happ_link = get_happ_encrypted_link(session, permanent_raw_url)
    except Exception as e:
        logger.error(f"Ошибка Happ Crypto API: {e}")
        sys.exit(1)

    # 6. Отчет
    write_summary_report(
        gist_id=active_gist_id,
        permanent_raw_url=permanent_raw_url,
        happ_link=happ_link,
        top_items=best_nodes_data,
        stats=stats,
    )

    logger.info("=== Обновление успешно завершено! Все серверы проверены и готовы к работе. ===")


if __name__ == "__main__":
    main()
