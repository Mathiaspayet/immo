#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
healthcheck.py — Sonde interrogee par Docker.

Sans elle, un conteneur qui demarre mais ne repond plus resterait « up » :
Watchtower deploierait une image cassee sans que rien ne le signale.
"""

import os
import sys
import urllib.request

PORT = os.environ.get("VEILLE_PORT", "8000")

try:
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/sante", timeout=8) as reponse:
        sys.exit(0 if reponse.status == 200 else 1)
except Exception as erreur:      # noqa: BLE001
    print(f"sonde en echec : {erreur}", file=sys.stderr)
    sys.exit(1)
