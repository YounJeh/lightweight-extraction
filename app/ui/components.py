from fasthtml.common import (
    A,
    Button,
    Div,
    Form,
    Input,
    Label,
    Li,
    P,
    Span,
    Table,
    Td,
    Textarea,
    Th,
    Tr,
    Ul,
)

from app.models import ExtractionResult, ExtractionRun, Field


def _examples_to_text(examples: list[str]) -> str:
    return "\n".join(examples)


def field_row(field: Field):
    return Tr(
        Td(
            Form(
                Input(name="title", value=field.title, required=True),
                Textarea(field.definition, name="definition", required=True),
                Textarea(
                    _examples_to_text(field.examples),
                    name="examples",
                    placeholder="Un exemple par ligne",
                ),
                Button("Mettre à jour", type="submit"),
                action=f"/fields/{field.id}/update",
                method="post",
            )
        ),
        Td(
            Form(
                Button("Supprimer", type="submit"),
                action=f"/fields/{field.id}/delete",
                method="post",
            )
        ),
    )


def fields_table(fields: list[Field]):
    if not fields:
        return Div("Aucun champ pour le moment — crée le premier ci-dessous.")
    return Table(
        Tr(Th("Titre / Définition / Exemples"), Th("Actions")),
        *[field_row(field) for field in fields],
    )


def field_create_form():
    return Form(
        Input(name="title", placeholder="Titre", required=True),
        Textarea(name="definition", placeholder="Définition", required=True),
        Textarea(name="examples", placeholder="Exemples (un par ligne)"),
        Button("Créer", type="submit"),
        action="/fields",
        method="post",
    )


def _field_checkbox(field: Field):
    input_id = f"field-{field.id}"
    return Div(
        Input(type="checkbox", name="field_ids", value=str(field.id), id=input_id),
        Label(field.title, **{"for": input_id}),
    )


def extraction_form(fields: list[Field]):
    if not fields:
        return Div(
            "Aucun champ disponible — ",
            A("crée d'abord un champ", href="/fields"),
            ".",
        )
    return Form(
        Input(type="file", name="pdf", accept="application/pdf", required=True),
        *[_field_checkbox(field) for field in fields],
        Button("Lancer l'extraction", type="submit"),
        action="/extraction",
        method="post",
    )


def _result_item(result: ExtractionResult):
    return Li(f"{result.field_title} : {result.value} ", Span("(mock)"))


def extraction_result(run: ExtractionRun):
    body = (
        Ul(*[_result_item(result) for result in run.results])
        if run.results
        else P("Aucun résultat (aucun champ n'avait été sélectionné).")
    )
    return Div(P(f"Document : {run.document_name}"), body)


def extraction_runs_list(runs: list[ExtractionRun]):
    if not runs:
        return Div("Aucune extraction pour le moment.")
    return Ul(
        *[
            Li(A(run.document_name, href=f"/extraction/runs/{run.id}"))
            for run in runs
        ]
    )
