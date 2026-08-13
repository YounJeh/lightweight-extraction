# Spec: UI moderne et épurée (Étape 1, inspirée de Claude.ai)

## Objectif

Refondre visuellement l'UI existante de l'Étape 1 (gestion des champs +
extraction PDF, voir [specs/mock-ui.md](mock-ui.md)) pour qu'elle ait un rendu
**moderne, épuré et cohérent**, inspiré de l'interface de Claude.ai (chat) :
sidebar de navigation, palette neutre chaleureuse, typographie claire,
composants en cartes arrondies, hiérarchie visuelle nette.

**Ce n'est pas une refonte fonctionnelle.** Aucune route, aucun modèle,
aucune logique métier ne change. Seuls `app/ui/layout.py`,
`app/ui/components.py`, un nouveau fichier CSS statique, et le câblage des
`hdrs` dans `app/main.py` sont concernés.

**Utilisateur cible :** identique à l'existant (développeur du projet en
validation interne).

**Succès =** les deux pages (Champs, Extraction) et la page de résultat ont
un rendu visuel moderne (sidebar, cartes, palette cohérente, focus states,
responsive basique), **sans régression fonctionnelle** — la suite pytest
existante (38 tests) passe sans modification de ses assertions.

## Hypothèses retenues

1. **Pas de nouvelle dépendance.** Pas de Tailwind/build JS/CDN de police —
   contraire à l'esprit "léger" de CLAUDE.md et au fait que le stack est figé
   (Python/uv uniquement, pas de toolchain Node). CSS artisanal, un seul
   fichier statique, police système.
2. **On désactive PicoCSS** (`pico=False` dans `fast_app()`) au profit d'une
   feuille de style maison, pour avoir un contrôle total du rendu plutôt que
   de surcharger les styles Pico existants.
3. **Le texte affiché ne change pas** — les tests vérifient du texte brut
   ("Erreur", "Aucun champ", "mock", noms de champs, `href="/fields"` /
   `href="/extraction"`). Seules la structure HTML (classes, wrapping) et le
   CSS changent ; aucune assertion de test n'est modifiée.
4. **Palette inspirée, pas copiée** — chaleureuse et neutre (crème / terracotta
   discret), sans logo ni nom "Claude"/"Anthropic" nulle part dans l'UI :
   inspiration esthétique uniquement, pas d'imitation de marque.
5. **Un seul thème (clair)** pour cette itération — pas de dark mode, pas de
   toggle (hors scope, peut être demandé ensuite).
6. **Responsive minimal** — la sidebar passe en barre horizontale en dessous
   de ~720px ; pas d'effort au-delà (pas de menu burger animé, etc.).

## Tech Stack

- Identique à l'existant : Python 3.12, FastHTML, SQLite, Pydantic, pytest, uv.
- Nouveau : un fichier `static/style.css` servi via la route statique déjà
  fournie par `fast_app()` (`app.static_route_exts`), référencé via `hdrs=`
  dans `fast_app()`. Aucune dépendance ajoutée dans `pyproject.toml`.

## Commands

Inchangées :
```
Install : uv sync
Dev     : uv run python -m app.main
Test    : uv run pytest -v
```

## Project Structure (fichiers concernés)

```
static/
  style.css          → nouveau, feuille de style unique (variables CSS, layout, composants)
app/
  main.py            → ajoute hdrs=(Link CSS, meta viewport) à fast_app(), pico=False
  ui/
    layout.py         → sidebar + structure de page (grid sidebar/main), nav avec état actif
    components.py      → markup des cartes (champs, formulaire, upload, résultats), classes CSS
```

## Design System

**Palette (variables CSS dans `:root`) :**
- `--bg-sidebar: #F4F1EA` (crème chaud)
- `--bg-main: #FDFCFA`
- `--bg-card: #FFFFFF`
- `--border: #E6E1D6`
- `--text-primary: #2B2823`
- `--text-secondary: #6F6B62`
- `--accent: #C15F3C` (terracotta discret — boutons primaires, liens, nav active)
- `--accent-hover: #A94E2F`
- `--danger-bg: #FBEAEA` / `--danger-text: #A6342A` (bannière d'erreur)
- `--badge-bg: #F0EEE7` / `--badge-text: #6F6B62` (badge "mock")

**Typographie :** pile système (`-apple-system, "Segoe UI", Helvetica, Arial,
sans-serif`), pas de police externe chargée.

**Layout :** grid `260px 1fr` (sidebar fixe / contenu), colonne de contenu
centrée `max-width: 760px` avec padding généreux — cf. la colonne centrée du
chat Claude.

**Composants :**
- Sidebar : nom de l'app + nav (Champs, Extraction) en items arrondis, état
  actif teinté `--accent`.
- Cartes : fond `--bg-card`, bordure `--border`, `border-radius: 12px`,
  padding 20-24px.
- Champs → une carte par champ (titre/définition/exemples éditables inline) +
  carte "Nouveau champ" ; actions Update (bouton primaire) / Delete (bouton
  texte danger).
- Extraction → carte upload (zone fichier + chips de sélection des champs) +
  carte historique des runs ; page résultat → liste libellé/valeur avec badge
  "mock".
- Bannière d'erreur : carte pleine largeur, fond `--danger-bg`, au-dessus du
  contenu.
- États vides : texte atténué + lien stylé bouton vers l'action pertinente.

## Code Style

```css
/* static/style.css */
:root {
  --bg-sidebar: #F4F1EA;
  --accent: #C15F3C;
  /* ... */
}

.card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 20px;
}

.btn-primary {
  background: var(--accent);
  color: #fff;
  border-radius: 8px;
}
```

```python
# app/ui/layout.py
def page(title: str, *content, active: str = ""):
    return (
        Title(title),
        Div(
            _sidebar(active),
            Main(H1(title), *content, cls="content"),
            cls="app-shell",
        ),
    )
```

Conventions : classes CSS en `kebab-case`, pas de style inline sauf cas
ponctuel, pas de JS ajouté (le style seul suffit à l'objectif).

## Testing Strategy

- Aucune nouvelle stratégie : la suite pytest existante (38 tests, routes +
  repositories + outils mock) doit continuer à passer **sans modification de
  ses assertions**, preuve que le texte/les hrefs n'ont pas changé.
- Vérification visuelle manuelle (navigateur ou capture d'écran) des trois
  vues (Champs, Extraction, Résultat) + un état d'erreur + un état vide,
  puisqu'aucun test automatisé ne couvre le rendu visuel.

## Boundaries

- **Toujours faire :**
  - Garder `uv run pytest` vert sans toucher aux assertions de test
    existantes.
  - Garder le texte affiché identique (labels, messages d'erreur, hrefs de
    nav) pour ne pas casser les tests d'intégration.
  - Rester sans dépendance externe (pas de CDN, pas de police externe, pas de
    build JS).
- **Demander avant de faire :**
  - Modifier un texte/label déjà couvert par une assertion de test.
  - Ajouter du JavaScript custom (au-delà de ce que FastHTML inclut déjà).
- **Ne jamais faire :**
  - Utiliser le nom "Claude" ou un logo Anthropic dans l'UI (inspiration
    esthétique uniquement).
  - Toucher aux fichiers `routes/`, `models.py`, `repository.py`,
    `extraction_repository.py`, `tools/` (hors scope de ce restyle).

## Success Criteria

- [x] `uv run pytest` passe (38/38), sans modification des fichiers de test.
- [x] Les pages Champs, Extraction et Résultat affichent la sidebar, les
      cartes, et la palette définies ci-dessus.
      *Vérifié via `curl` contre le serveur réel (pas d'affichage GUI
      disponible dans cet environnement) : état vide, formulaire, chips de
      sélection, page résultat avec badge mock.*
- [x] La bannière d'erreur et les états vides sont visuellement stylés (pas
      du texte brut sans mise en forme).
      *`.banner-error` (titre vide) et `.empty-state` (aucun champ) vérifiés.*
- [x] Aucune dépendance ajoutée à `pyproject.toml`.
- [x] Aucune requête réseau externe déclenchée par le rendu de la page (pas
      de police/CDN externe). *Police système uniquement ; les scripts HTMX/
      surreal chargés depuis un CDN sont un comportement par défaut de
      FastHTML préexistant, hors scope de ce restyle.*

## Open Questions

Aucune bloquante — direction validée par l'utilisateur ("plus moderne tout en
restant épurée, inspiré de l'UI de Claude chat"). Palette/typographie
choisies par défaut ci-dessus, ajustables sur retour utilisateur.
