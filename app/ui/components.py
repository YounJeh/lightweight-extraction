from fasthtml.common import (
    A,
    Button,
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


def _field_checkbox(field: Field):
    input_id = f"field-{field.id}"
    return Label(
        Input(type="checkbox", name="field_ids", value=str(field.id), id=input_id),
        field.title,
        cls="chip",
        **{"for": input_id},
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
                Div(*[_field_checkbox(field) for field in fields], cls="chip-list"),
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
