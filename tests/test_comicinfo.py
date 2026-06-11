import xml.etree.ElementTree as ET
from types import SimpleNamespace

from jm_downloader.comicinfo import build_comicinfo_xml


def test_build_comicinfo_xml_escapes_and_maps_fields():
    album = SimpleNamespace(
        id="100",
        title="Series & Name",
        authors=["Author A", "Author B"],
        tags=["tag<1"],
        works=["work"],
        actors=["actor"],
        description="Summary > text",
        pub_date="2024-05-06",
    )
    photo = SimpleNamespace(id="200")

    xml = build_comicinfo_xml(
        album=album,
        photo=photo,
        title="Chapter <One>",
        number=1,
        count=2,
        page_count=12,
        web="https://example.test/album/100",
    )
    root = ET.fromstring(xml)

    assert root.findtext("Series") == "Series & Name"
    assert root.findtext("Title") == "Chapter <One>"
    assert root.findtext("Writer") == "Author A, Author B"
    assert root.findtext("Tags") == "tag<1, work, actor"
    assert root.findtext("Manga") == "Webtoon"
    assert root.findtext("Year") == "2024"
    assert root.findtext("Month") == "5"
    assert root.findtext("Day") == "6"
