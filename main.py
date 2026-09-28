#!/usr/bin/env python3
"""
Autonomous Happ Proxy Subscription Generator & Updater
Author: Senior DevOps & Python Engineer
License: MIT
"""

import os
import re
import sys
import time
import base64
import logging
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- Configuration & Sources ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("HappUpdater")

# Reliable, active public sources with VLESS, Trojan, SS, VMess, Hysteria2
SOURCES = [
    "https://raw.githubusercontent.com/Pawdroid/Free-servers/main/sub",
    "https://raw.githubusercontent.com/ermaozi/get_subscribe/main/subscribe/v2ray.txt",
    "https://raw.githubusercontent.com/ts-sf/fly/main/v2",
    "https://raw.githubusercontent.com/freefq/free/master/v2",
    "https://raw.githubusercontent.com/mahdibland/V2RayAggregator/master/sub/sub_merge.txt",
]

SUPPORTED_SCHEMES = (
    "vless://",
    "trojan://",
    "ss://",
    "vmess://",
    "hysteria2://",
    "hy2://",
    "tuic://",
)

MAX_NODES = 250  # Balanced limit for optimal mobile performance and fast subscription parsing
HAPP_CRYPTO_API = "https://crypto.happ.su/api-v2.php"
GIST_FILENAME = "subscription.txt"
GIST_DESCRIPTION = "Happ Proxy Auto-Updated Subscription [Managed by GitHub Actions]"


def get_http_session() -> requests.Session:
    """Create a resilient requests session with automatic retries and realistic headers."""
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
    """Detect and decode Base64 encoded subscription payloads with padding auto-fix."""
    compact = re.sub(r"\s+", "", raw_text)
    if not compact:
        return raw_text

    # Pad if missing
    missing_padding = len(compact) % 4
    if missing_padding:
        compact += "=" * (4 - missing_padding)

    try:
        decoded_bytes = base64.b64decode(compact, validate=False)
        decoded_str = decoded_bytes.decode("utf-8", errors="replace")
        # Ensure decoded output contains proxy configurations
        if any(scheme in decoded_str for scheme in SUPPORTED_SCHEMES):
            return decoded_str
    except Exception:
        pass

    return raw_text


def fetch_source_configs(session: requests.Session, url: str) -> List[str]:
    """Fetch nodes from a remote URL with error handling and format normalization."""
    logger.info(f"Fetching nodes from: {url}")
    configs: List[str] = []
    try:
        response = session.get(url, timeout=12)
        if response.status_code != 200:
            logger.warning(f"Failed to fetch {url} (HTTP {response.status_code})")
            return []

        text = response.text
        # Decode base64 if needed
        text = try_decode_base64(text)

        for line in text.splitlines():
            line = line.strip()
            if any(line.startswith(scheme) for scheme in SUPPORTED_SCHEMES):
                configs.append(line)

        logger.info(f"  -> Extracted {len(configs)} raw configs from {url}")
    except requests.RequestException as e:
        logger.warning(f"Network error while fetching {url}: {e}")
    except Exception as e:
        logger.warning(f"Unexpected error while processing {url}: {e}")

    return configs


def is_valid_node(config_line: str) -> bool:
    """Filter out broken, loopback or placeholder configs."""
    if len(config_line) < 20:
        return False

    # VMess configurations are base64 JSONs after prefix
    if config_line.startswith("vmess://"):
        return True

    # Filter out localhost, loopbacks and obvious invalid targets
    invalid_patterns = (
        "@127.0.0.1",
        "@localhost",
        "@0.0.0.0",
        "@::1",
        ":0",
    )
    if any(pat in config_line for pat in invalid_patterns):
        return False

    # Standard URI checks
    if "@" not in config_line:
        return False

    return True


def get_node_dedup_key(config_line: str) -> str:
    """
    Extract the core connection identity (server + port + credentials),
    ignoring cosmetic user tags (#remarks) to prevent duplicates.
    """
    core = config_line.split("#", 1)[0].strip()
    return core


def aggregate_and_filter_nodes(session: requests.Session) -> Tuple[List[str], Dict[str, int]]:
    """Download, validate, deduplicate, and rank proxy configurations."""
    all_raw: List[str] = []
    for source in SOURCES:
        all_raw.extend(fetch_source_configs(session, source))

    seen_keys: Set[str] = set()
    unique_nodes: List[str] = []
    stats: Dict[str, int] = {scheme.replace("://", ""): 0 for scheme in SUPPORTED_SCHEMES}

    for line in all_raw:
        if not is_valid_node(line):
            continue

        key = get_node_dedup_key(line)
        if key in seen_keys:
            continue

        seen_keys.add(key)
        unique_nodes.append(line)

        # Track stats
        for scheme in SUPPORTED_SCHEMES:
            if line.startswith(scheme):
                stats[scheme.replace("://", "")] += 1
                break

    # Prioritize nodes: VLESS / Trojan / Hysteria2 first, then VMess / Shadowsocks
    def sort_priority(item: str) -> int:
        if item.startswith(("vless://", "hysteria2://", "hy2://")):
            return 0
        if item.startswith("trojan://"):
            return 1
        if item.startswith("ss://"):
            return 2
        return 3

    unique_nodes.sort(key=sort_priority)

    # Cap to MAX_NODES
    filtered_nodes = unique_nodes[:MAX_NODES]
    logger.info(f"Total raw fetched: {len(all_raw)} | Deduplicated unique: {len(unique_nodes)} | Selected: {len(filtered_nodes)}")
    logger.info(f"Node distribution: {stats}")

    return filtered_nodes, stats


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
    """
    Creates or updates a secret GitHub Gist with the subscription.
    Returns: (gist_id, permanent_raw_url)
    """
    headers = {
        "Authorization": f"Bearer {gist_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # 1. If GIST_ID is provided, update it directly
    if gist_id:
        logger.info(f"Updating existing Gist ID: {gist_id}")
        url = f"https://api.github.com/gists/{gist_id}"
        payload = {
            "description": GIST_DESCRIPTION,
            "files": {
                GIST_FILENAME: {
                    "content": content_b64
                }
            }
        }
        res = session.patch(url, headers=headers, json=payload, timeout=15)
        if res.status_code == 200:
            data = res.json()
            raw_url = data["files"][GIST_FILENAME]["raw_url"]
            permanent_url = re.sub(r"/raw/[0-9a-f]{40}/", "/raw/", raw_url)
            return gist_id, permanent_url
        else:
            logger.error(f"Failed to update Gist {gist_id}: {res.status_code} {res.text}")
            raise RuntimeError(f"Gist update failed with status {res.status_code}")

    # 2. Check if a managed Gist already exists under this user
    logger.info("GIST_ID not provided. Checking for existing managed Gists on account...")
    res = session.get("https://api.github.com/gists", headers=headers, timeout=15)
    if res.status_code == 200:
        gists = res.json()
        for g in gists:
            if GIST_FILENAME in g.get("files", {}) or g.get("description") == GIST_DESCRIPTION:
                found_id = g["id"]
                logger.info(f"Found existing managed Gist: {found_id}. Reusing it.")
                return sync_github_gist(session, gist_token, found_id, content_b64)

    # 3. Create a new secret Gist if none found
    logger.info("Creating a new secret GitHub Gist...")
    create_payload = {
        "description": GIST_DESCRIPTION,
        "public": False,
        "files": {
            GIST_FILENAME: {
                "content": content_b64
            }
        }
    }
    create_res = session.post("https://api.github.com/gists", headers=headers, json=create_payload, timeout=15)
    if create_res.status_code == 201:
        data = create_res.json()
        new_id = data["id"]
        raw_url = data["files"][GIST_FILENAME]["raw_url"]
        permanent_url = re.sub(r"/raw/[0-9a-f]{40}/", "/raw/", raw_url)
        logger.info(f"Successfully created Gist with ID: {new_id}")
        return new_id, permanent_url
    else:
        logger.error(f"Failed to create Gist: {create_res.status_code} {create_res.text}")
        raise RuntimeError(f"Gist creation failed with status {create_res.status_code}")


def get_happ_encrypted_link(session: requests.Session, permanent_raw_url: str) -> str:
    """Send the permanent subscription RAW URL to Happ API and obtain happ://crypt5/... link."""
    logger.info(f"Requesting Happ encryption for URL: {permanent_raw_url}")
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
            logger.error(f"Happ API returned status {res.status_code}: {res.text}")
    except Exception as e:
        logger.error(f"Failed to communicate with Happ API: {e}")

    raise RuntimeError("Could not retrieve encrypted link from Happ Crypto API")


def write_summary_report(
    gist_id: str,
    permanent_raw_url: str,
    happ_link: str,
    node_count: int,
    stats: Dict[str, int],
):
    """Write summary to GitHub Actions Step Summary and local markdown artifact."""
    summary_md = f"""# 🚀 Happ Proxy Auto-Updated Subscription

**Статус:** ✅ Успешно обновлено  
**Серверов в подписке:** `{node_count}`  
**Дата обновления (UTC):** `{time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}`

---

### 📲 Ссылка для клиента Happ (Добавьте 1 раз):
```text
{happ_link}
```

---

### 🌐 Постоянный адрес подписки (Gist RAW):
```text
{permanent_raw_url}
```

### 📊 Распределение протоколов:
| Протокол | Количество узлов |
|---|---|
| **VLESS** | {stats.get('vless', 0)} |
| **Trojan** | {stats.get('trojan', 0)} |
| **Shadowsocks** | {stats.get('ss', 0)} |
| **VMess** | {stats.get('vmess', 0)} |
| **Hysteria2 / TUIC** | {stats.get('hysteria2', 0) + stats.get('hy2', 0) + stats.get('tuic', 0)} |

> [!TIP]
> Скопируйте ссылку `happ://crypt5/...` и импортируйте её в клиент Happ.
> Поскольку постоянный RAW-URL не меняется, подписка в приложении будет обновляться автоматически при каждом запросе!
"""

    # Print to console
    print("\n" + "=" * 80)
    print("HAPP PROXY SUBSCRIPTION LINK:")
    print(happ_link)
    print("=" * 80 + "\n")

    # Save to local files
    with open("happ_link.txt", "w", encoding="utf-8") as f:
        f.write(happ_link + "\n")

    with open("HAPP_SUBSCRIPTION.md", "w", encoding="utf-8") as f:
        f.write(summary_md)

    # Write to GitHub Step Summary if running in GitHub Actions
    github_step_summary = os.getenv("GITHUB_STEP_SUMMARY")
    if github_step_summary:
        try:
            with open(github_step_summary, "a", encoding="utf-8") as f:
                f.write(summary_md)
            logger.info("Wrote summary to GitHub Actions Step Summary.")
        except Exception as e:
            logger.warning(f"Could not write to GITHUB_STEP_SUMMARY: {e}")


def main():
    logger.info("=== Starting Happ Proxy Generator ===")
    session = get_http_session()

    # 1. Fetch, deduplicate and sanitize nodes
    nodes, stats = aggregate_and_filter_nodes(session)
    if not nodes:
        logger.error("No valid proxy nodes could be harvested. Aborting.")
        sys.exit(1)

    # 2. Encode to Base64
    b64_content = encode_subscription(nodes)
    logger.info(f"Encoded subscription length: {len(b64_content)} chars")

    # 3. GitHub Gist synchronization
    gist_token = os.getenv("GIST_TOKEN")
    gist_id = os.getenv("GIST_ID")

    if not gist_token:
        logger.warning("GIST_TOKEN is not set in environment. Running in DRY-RUN mode.")
        with open("subscription.txt", "w", encoding="utf-8") as f:
            f.write(b64_content)
        logger.info("Saved local 'subscription.txt'. To upload to Gist, set GIST_TOKEN.")
        return

    try:
        active_gist_id, permanent_raw_url = sync_github_gist(
            session=session,
            gist_token=gist_token,
            gist_id=gist_id,
            content_b64=b64_content,
        )
        logger.info(f"Permanent Gist RAW URL: {permanent_raw_url}")
    except Exception as e:
        logger.error(f"GitHub Gist synchronization failed: {e}")
        sys.exit(1)

    # 4. Request Happ Crypto API
    try:
        happ_link = get_happ_encrypted_link(session, permanent_raw_url)
    except Exception as e:
        logger.error(f"Happ encryption failed: {e}")
        sys.exit(1)

    # 5. Output and report
    write_summary_report(
        gist_id=active_gist_id,
        permanent_raw_url=permanent_raw_url,
        happ_link=happ_link,
        node_count=len(nodes),
        stats=stats,
    )

    logger.info("=== Process completed successfully ===")


if __name__ == "__main__":
    main()
