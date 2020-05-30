import configparser
import os
import tempfile
import urllib.request
import xml.dom.minidom
import xml.etree.ElementTree as ET
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from tinytag import TinyTag
import gevent

dir_path = os.path.dirname(os.path.realpath(__file__))

CONFIG = configparser.ConfigParser()
CONFIG.read(os.path.join(dir_path, 'setting.cfg'))
USE_GEVENT = CONFIG['common'].getboolean('use_gevent')


def get_site_list(file_name):
    root = ET.parse(file_name).getroot()
    site_list = []
    for child in root:
        if child.tag == "site":
            site_list.append(child.text)
    return site_list


def get_mp3_genre_and_title(mp3_filename):
    audio_tag = TinyTag.get(mp3_filename)
    if audio_tag.genre is None:
        audio_tag.genre = "Undefined"
    if audio_tag.title is None:
        audio_tag.title = "No-title"
    return audio_tag.genre, audio_tag.title


def collect_all_links_from_html(html_page):
    soup = BeautifulSoup(html_page, 'html.parser')
    return [x.get('href') for x in soup.find_all('a')]


def get_all_links_from_url(url):
    try:
        main_page_req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        html_page = urllib.request.urlopen(main_page_req)
        return collect_all_links_from_html(html_page)
    except urllib.error.HTTPError:
        return []


def convert_link_to_absolute(base_url, link):
    url = urllib.parse.urljoin(base_url, link)
    parsed_url = urllib.request.urlparse(url)
    if parsed_url.scheme != "file":
        return parsed_url.scheme + "://" + parsed_url.netloc + urllib.parse.quote(parsed_url.path)
    else:
        return url


def convert_links_to_absolute(base_url, links):
    return [convert_link_to_absolute(base_url, link) for link in links]


def get_mp3_links(links, digest_level, *, use_gevent):
    visited_links = set()
    mp3_links = []

    def _get_mp3_links(url, level):
        visited_links.add(url)
        _links = convert_links_to_absolute(url, get_all_links_from_url(url))
        links_to_visit = []
        for link in _links:
            if link.endswith(".mp3"):
                mp3_links.append(link)
            elif level > 1:
                req = urllib.request.Request(url, method="HEAD", headers={'User-Agent': 'Mozilla/5.0'})
                response = urllib.request.urlopen(req)
                if link.endswith("html") or response.getheader("Content-Type").startswith("text/html"):
                    links_to_visit.append(link)
        if level > 1:
            for link in links_to_visit:
                if link not in visited_links:
                    _get_mp3_links(link, level - 1)

    if use_gevent:
        jobs = [gevent.spawn(_get_mp3_links, url, digest_level) for url in links]
        gevent.joinall(jobs)
    else:
        for url in links:
            _get_mp3_links(url, digest_level)
    return mp3_links


def analyze_mp3_from_links(mp3_links, *, use_gevent):
    analyzed_mp3_sorted_by_genre = {}
    tmp_dir = tempfile.TemporaryDirectory(suffix='mp3')

    def _analyze_mp3(mp3_link):
        file_name = os.path.basename(urllib.parse.urlparse(mp3_link).path)
        try:
            print(f"Load {file_name}")
            req = urllib.request.Request(mp3_link, headers={'User-Agent': 'Mozilla/5.0', "Range": "bytes:0-4000"})
            with urllib.request.urlopen(req) as response, \
                    tempfile.NamedTemporaryFile(mode="w+b", delete=False, dir=tmp_dir.name) as out_file:
                data = response.read()
                out_file.write(data)
                tmp_filename = out_file.name
            genre, title = get_mp3_genre_and_title(tmp_filename)
            if genre not in analyzed_mp3_sorted_by_genre:
                analyzed_mp3_sorted_by_genre[genre] = []
            analyzed_mp3_sorted_by_genre[genre].append({"filename": file_name, "title": title, "link": mp3_link})
        except URLError:
            pass

    if use_gevent:
        jobs = [gevent.spawn(_analyze_mp3, mp3_link) for mp3_link in mp3_links]
        gevent.joinall(jobs)
    else:
        for mp3_link in mp3_links:
            _analyze_mp3(mp3_link)
    tmp_dir.cleanup()
    return analyzed_mp3_sorted_by_genre


def generate_xml(sorted_by_genre_mp3):
    root = ET.Element('Playlist')
    for key, value in sorted_by_genre_mp3.items():
        genre_node = ET.SubElement(root, 'Genre', {'name': key})
        for mp3_info in value:
            mp3_info_node = ET.SubElement(genre_node, 'music')
            ET.SubElement(mp3_info_node, 'filename').text = mp3_info['filename']
            ET.SubElement(mp3_info_node, 'title').text = mp3_info['title']
            ET.SubElement(mp3_info_node, 'link').text = mp3_info['link']
    mydata = ET.tostring(root, encoding="unicode")
    preparsed = xml.dom.minidom.parseString(mydata)
    return preparsed.toprettyxml().encode("utf-8")


def get_result(sorted_by_genre_mp3, result_file):
    final_res = generate_xml(sorted_by_genre_mp3)
    result_file.write(final_res)


def main(input_filename, digest_level):
    site_list = get_site_list(input_filename)
    mp3_links = get_mp3_links(site_list, digest_level, use_gevent=USE_GEVENT)
    analyzed_res = analyze_mp3_from_links(mp3_links, use_gevent=USE_GEVENT)
    with open("result.xml", "wb") as res_file:
        get_result(analyzed_res, res_file)


main('data.xml', 1)
