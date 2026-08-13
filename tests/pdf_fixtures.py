import pymupdf

# Valeurs connues à l'avance, utilisées comme oracle par le test offline
# (Task 3, relecture) et par le test live LangExtract (Task 5).
SAMPLE_CONTRACT_FIELDS = {
    "Titre du contrat": "Contrat de bail",
    "Nom du locataire": "Julien Moreau",
    "Date de signature": "12 janvier 2024",
}


def build_sample_contract_pdf() -> bytes:
    """PDF factice de 2 pages avec les valeurs de SAMPLE_CONTRACT_FIELDS
    réparties sur les deux pages, pour exercer le grounding multi-page."""
    doc = pymupdf.open()

    page1 = doc.new_page()
    page1.insert_text((72, 72), "CONTRAT DE BAIL")
    page1.insert_text((72, 100), "Titre du contrat: Contrat de bail")
    page1.insert_text((72, 128), "Nom du locataire: Julien Moreau")

    page2 = doc.new_page()
    page2.insert_text((72, 72), "Conditions particulieres")
    page2.insert_text((72, 100), "Date de signature: 12 janvier 2024")

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes
