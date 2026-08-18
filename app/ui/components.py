from fasthtml.common import (
    A,
    Button,
    Details,
    Div,
    Form,
    Input,
    Label,
    Li,
    Option,
    P,
    Script,
    Select,
    Span,
    Summary,
    Table,
    Tbody,
    Td,
    Textarea,
    Th,
    Thead,
    Tr,
    Ul,
)

from app.models import ExtractionResult, ExtractionRun, Field, FieldExample

_FIELD_TYPES = [
    ("text", "Texte"),
    ("int", "Entier"),
    ("float", "Décimal"),
    ("bool", "Booléen"),
    ("date", "Date"),
]


def _examples_to_text(examples: list[FieldExample]) -> str:
    return "\n".join(e.context for e in examples)


def _type_select(field_id: str, selected: str = "text"):
    return Select(
        *[
            Option(label, value=value, selected=(value == selected))
            for value, label in _FIELD_TYPES
        ],
        name="type",
        id=field_id,
    )


def error_banner(message: str):
    return Div(f"Erreur : {message}", cls="banner-error")


def field_row(field: Field):
    return Div(
        Form(
            Label("Clé", **{"for": f"key-{field.id}"}),
            Input(name="key", value=field.key, required=True, id=f"key-{field.id}"),
            Label("Section", **{"for": f"section-{field.id}"}),
            Input(name="section", value=field.section or "", id=f"section-{field.id}"),
            Label("Titre", **{"for": f"title-{field.id}"}),
            Input(name="title", value=field.title, required=True, id=f"title-{field.id}"),
            Label("Définition", **{"for": f"def-{field.id}"}),
            Textarea(field.definition, name="definition", required=True, id=f"def-{field.id}"),
            Label("Exemples (un par ligne)", **{"for": f"ex-{field.id}"}),
            Textarea(
                _examples_to_text(field.examples),
                name="examples",
                placeholder="Un exemple par ligne",
                id=f"ex-{field.id}",
            ),
            Label("Type", **{"for": f"type-{field.id}"}),
            _type_select(f"type-{field.id}", selected=field.type),
            Div(
                Button("Mettre à jour", type="submit"),
                cls="card-footer",
            ),
            action=f"/fields/{field.id}/update",
            method="post",
        ),
        Form(
            Div(
                Button("Supprimer", type="submit", cls="btn-danger"),
                cls="card-footer",
            ),
            action=f"/fields/{field.id}/delete",
            method="post",
        ),
        cls="card",
    )


def fields_table(fields: list[Field]):
    if not fields:
        return Div(
            "Aucun champ pour le moment — crée le premier ci-dessus.",
            cls="empty-state",
        )
    return Div(*[field_row(field) for field in fields], cls="stack")


def field_create_form():
    return Div(
        Div("Nouveau champ", cls="card-title"),
        Form(
            Label("Clé", **{"for": "new-key"}),
            Input(name="key", placeholder="Clé", required=True, id="new-key"),
            Label("Section", **{"for": "new-section"}),
            Input(name="section", placeholder="Section", id="new-section"),
            Label("Titre", **{"for": "new-title"}),
            Input(name="title", placeholder="Titre", required=True, id="new-title"),
            Label("Définition", **{"for": "new-definition"}),
            Textarea(
                name="definition",
                placeholder="Définition",
                required=True,
                id="new-definition",
            ),
            Label("Exemples (un par ligne)", **{"for": "new-examples"}),
            Textarea(
                name="examples",
                placeholder="Exemples (un par ligne)",
                id="new-examples",
            ),
            Label("Type", **{"for": "new-type"}),
            _type_select("new-type"),
            Div(Button("Créer", type="submit"), cls="card-footer"),
            action="/fields",
            method="post",
        ),
        cls="card",
    )


def field_import_form():
    return Div(
        Div("Importer des champs", cls="card-title"),
        Form(
            Label("Fichier (.csv, .tsv, .xlsx)", **{"for": "import-file"}),
            Input(
                type="file",
                name="file",
                accept=".csv,.tsv,.xlsx",
                required=True,
                id="import-file",
            ),
            Div(Button("Importer", type="submit"), cls="card-footer"),
            action="/fields/import",
            method="post",
        ),
        cls="card",
    )


_OTHER_SECTION = "Autres"


def _group_fields_by_section(fields: list[Field]) -> list[tuple[str, list[Field]]]:
    groups: dict[str, list[Field]] = {}
    for field in fields:
        groups.setdefault(field.section or _OTHER_SECTION, []).append(field)
    return [(name, groups[name]) for name in sorted(groups)]


def _field_checkbox_row(field: Field):
    input_id = f"field-{field.id}"
    return Label(
        Input(
            type="checkbox", name="field_ids", value=str(field.id), id=input_id, checked=True
        ),
        field.title,
        cls="field-row",
        **{"for": input_id},
    )


def _field_section_group(section: str, fields: list[Field]):
    return Details(
        Summary(
            Span(section, cls="field-group-name"),
            Span(f"{len(fields)}/{len(fields)} sélectionnés", cls="field-group-count"),
        ),
        Div(
            Button(
                "Tout sélectionner", type="button", data_select="all", cls="field-group-toggle"
            ),
            Button(
                "Tout désélectionner",
                type="button",
                data_select="none",
                cls="field-group-toggle",
            ),
            cls="field-group-actions",
        ),
        Div(*[_field_checkbox_row(f) for f in fields], cls="field-group-list"),
        cls="field-group",
    )


def _field_group_selection_script():
    return Script(
        """
        (function () {
          var container = document.querySelector(".field-groups");
          if (!container) return;

          function updateCount(group) {
            var boxes = group.querySelectorAll('input[type="checkbox"]');
            var checked = group.querySelectorAll('input[type="checkbox"]:checked').length;
            var countEl = group.querySelector(".field-group-count");
            if (countEl) countEl.textContent = checked + "/" + boxes.length + " sélectionnés";
          }

          container.addEventListener("change", function (e) {
            if (e.target.type !== "checkbox") return;
            var group = e.target.closest(".field-group");
            if (group) updateCount(group);
          });

          container.addEventListener("click", function (e) {
            var button = e.target.closest("[data-select]");
            if (!button) return;
            var group = button.closest(".field-group");
            if (!group) return;
            var checked = button.dataset.select === "all";
            group.querySelectorAll('input[type="checkbox"]').forEach(function (cb) {
              cb.checked = checked;
            });
            updateCount(group);
          });
        })();
        """
    )


def _extraction_loading_script():
    return Script(
        """
        (function () {
          var form = document.getElementById("extraction-form");
          var submitBtn = document.getElementById("extraction-submit-btn");
          if (!form || !submitBtn) return;
          form.addEventListener("submit", function () {
            submitBtn.disabled = true;
            submitBtn.textContent = "Extraction en cours…";
          });
        })();
        """
    )


def extraction_form(fields: list[Field]):
    if not fields:
        return Div(
            Div(
                "Aucun champ disponible — ",
                A("crée d'abord un champ", href="/fields"),
                ".",
            ),
            cls="empty-state",
        )
    return (
        Div(
            Div("Nouvelle extraction", cls="card-title"),
            Form(
                Label("Document PDF", **{"for": "pdf-input"}),
                Input(
                    type="file",
                    name="pdf",
                    accept="application/pdf",
                    required=True,
                    id="pdf-input",
                ),
                Label("Champs à extraire"),
                Div(
                    *[
                        _field_section_group(section, section_fields)
                        for section, section_fields in _group_fields_by_section(fields)
                    ],
                    cls="field-groups",
                ),
                Div(
                    Button(
                        "Lancer l'extraction",
                        type="submit",
                        id="extraction-submit-btn",
                    ),
                    cls="card-footer",
                ),
                id="extraction-form",
                action="/extraction",
                method="post",
            ),
            cls="card",
        ),
        _extraction_loading_script(),
        _field_group_selection_script(),
    )


def _result_grounding(result: ExtractionResult):
    if result.page_number is None:
        return Span("—", cls="result-grounding-empty")
    return Span(
        Span(f"p. {result.page_number}", cls="result-page"),
        f" · {result.text_position}",
        cls="result-grounding",
    )


def _result_type(result: ExtractionResult):
    if result.value_type is None:
        return Span("—", cls="result-grounding-empty")
    return Span(result.value_type, cls="badge")


def _result_row(result: ExtractionResult):
    displayed_value = result.typed_value or result.value
    value_attrs = {"cls": "result-value"}
    if result.type_error:
        value_attrs = {"cls": "result-value result-value-error", "title": result.type_error}
    elif displayed_value != result.value:
        # La valeur typée est plus courte/normalisée que le texte groundé —
        # ce dernier reste consultable au survol comme contexte.
        value_attrs["title"] = result.value
    return Tr(
        Td(result.field_title, cls="result-field"),
        Td(displayed_value, **value_attrs),
        Td(_result_type(result), cls="result-type"),
        Td(Span(result.source, cls="badge"), cls="result-source"),
        Td(_result_grounding(result), cls="result-location"),
    )


def extraction_result(run: ExtractionRun):
    if not run.results:
        body = P("Aucun résultat (aucun champ n'avait été sélectionné).")
    else:
        body = Div(
            Table(
                Thead(
                    Tr(
                        Th("Champ"),
                        Th("Valeur"),
                        Th("Type"),
                        Th("Source"),
                        Th("Localisation"),
                    )
                ),
                Tbody(*[_result_row(result) for result in run.results]),
                cls="result-table",
            ),
            cls="result-table-wrap",
        )
    return Div(
        Div(f"Document : {run.document_name}", cls="card-title"),
        body,
        cls="card",
    )


def extraction_runs_list(runs: list[ExtractionRun]):
    if not runs:
        return Div("Aucune extraction pour le moment.", cls="empty-state")
    return Div(
        Div("Historique", cls="card-title"),
        Div(
            Form(
                Button("Nettoyer l'historique", type="submit", cls="btn-danger"),
                action="/extraction/runs/delete",
                method="post",
            ),
            cls="card-actions",
        ),
        Ul(
            *[
                Li(A(run.document_name, href=f"/extraction/runs/{run.id}"))
                for run in runs
            ],
            cls="run-list",
        ),
        cls="card",
    )
