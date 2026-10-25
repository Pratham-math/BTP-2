"""Only trusted generated fixtures are decoded outside the parser container."""
from pypdf import PdfWriter
from PIL import Image
from sqlalchemy import select

from server.database import Source
from server.ingestion.previews import pdf_previews
from test_platform import platform, headers


def test_page_previews_preserve_inventory_and_bound_dimensions(tmp_path):
    source = tmp_path / 'fixture.pdf'
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    writer.add_blank_page(width=5000, height=4000)
    writer.write(source)
    manifest = pdf_previews(source, tmp_path)
    assert [x['page'] for x in manifest] == [1, 2]
    for row in manifest:
        with Image.open(tmp_path / row['file']) as image:
            assert image.format == 'PNG' and max(image.size) <= 1600


def test_private_page_image_access_and_corrections_are_source_scoped(platform):
    client, factory, ids = platform
    source = client.post('/api/sources', headers=headers('alice'), json={
        'title': 'Controlled fixture notes', 'kind': 'text', 'text': 'A corrected source page used only in fixtures.'}).json()
    key = f"sources/{ids['alice']}/{source['id']}/previews/page-1.png"
    with factory.begin() as db:
        db.get(Source, source['id']).metadata_json = {'preview_keys': [key]}
    source['evidence'][0]['image_key'] = key
    corrected = client.put(f"/api/sources/{source['id']}/preview", headers=headers('alice'), json={
        'expected_version': 1, 'evidence': source['evidence'], 'confirm': True, 'note': 'Compared with fixture original page.'})
    assert corrected.status_code == 200, corrected.text
    url = f"/api/sources/{source['id']}/evidence/{source['evidence'][0]['id']}/image"
    assert client.get(url, headers=headers('bob')).status_code == 404
    response = client.get(url, headers=headers('alice'))
    assert response.status_code == 200 and key in response.json()['url']
    assert client.get(url.replace(source['evidence'][0]['id'], 'nonexistent'), headers=headers('alice')).status_code == 404
