# -*- coding: utf-8 -*-
"""Publie une release GitHub avec ses pieces jointes, puis la relit.

Usage : python publier_release.py TAG "Titre" notes.md fichier1 [fichier2...]

Le token vient du gestionnaire d'identifiants git (jamais affiche).
Idempotent : une release deja existante est reutilisee, une piece
jointe de meme nom est remplacee (supprimee puis renvoyee).
"""
import os
import subprocess
import sys

import requests

REPO = "yohandry12/ACL_Record"
API = f"https://api.github.com/repos/{REPO}"
BRANCHE = "hd-ultrahd-screen"


def token():
    out = subprocess.run(['git', 'credential', 'fill'],
                         input='protocol=https\nhost=github.com\n',
                         capture_output=True, text=True).stdout
    champs = dict(l.split('=', 1) for l in out.splitlines() if '=' in l)
    t = champs.get('password')
    if not t:
        sys.exit("token introuvable dans le gestionnaire d'identifiants")
    return t


def main():
    tag, titre, notes_path, *fichiers = sys.argv[1:]
    notes = open(notes_path, encoding='utf-8').read()
    h = {'Authorization': f'Bearer {token()}',
         'Accept': 'application/vnd.github+json'}

    r = requests.get(f"{API}/releases/tags/{tag}", headers=h, timeout=20)
    if r.status_code == 200:
        rel = r.json()
        print(f"release {tag} existante, reutilisee")
    else:
        r = requests.post(f"{API}/releases", headers=h, timeout=30, json={
            'tag_name': tag, 'target_commitish': BRANCHE, 'name': titre,
            'body': notes, 'draft': False, 'prerelease': False})
        r.raise_for_status()
        rel = r.json()
        print(f"release {tag} creee : {rel['html_url']}")

    existants = {a['name']: a for a in rel.get('assets', [])}
    upload_url = rel['upload_url'].split('{')[0]

    for chemin in fichiers:
        nom = os.path.basename(chemin)
        taille = os.path.getsize(chemin)
        if nom in existants:
            requests.delete(f"{API}/releases/assets/{existants[nom]['id']}",
                            headers=h, timeout=30).raise_for_status()
            print(f"  {nom} : ancienne piece jointe supprimee")
        print(f"  envoi de {nom} ({taille / 1048576:.1f} Mo) ...", flush=True)
        with open(chemin, 'rb') as f:
            r = requests.post(upload_url, params={'name': nom},
                              headers={**h, 'Content-Type': 'application/octet-stream',
                                       'Content-Length': str(taille)},
                              data=f, timeout=1800)
        r.raise_for_status()
        recu = r.json()
        etat = 'OK' if recu['size'] == taille else f"TAILLE DIFFERENTE ({recu['size']})"
        print(f"  {nom} : {recu['size']} octets, {etat}")

    # Relecture independante : ce que verra download_setup
    r = requests.get(f"{API}/releases/tags/{tag}", headers=h, timeout=20)
    r.raise_for_status()
    print("\n=== release relue ===")
    for a in r.json()['assets']:
        print(f"  {a['name']:40} {a['size']:>12} octets  {a['browser_download_url']}")


if __name__ == '__main__':
    main()
