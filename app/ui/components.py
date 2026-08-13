from fasthtml.common import Button, Div, Form, Input, Table, Td, Textarea, Th, Tr

from app.models import Field


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
