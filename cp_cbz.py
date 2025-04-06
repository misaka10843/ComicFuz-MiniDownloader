import os
from pathlib import Path

from cbz.comic import ComicInfo
from cbz.constants import PageType, YesNo, Manga, AgeRating, Format
from cbz.page import PageInfo


def package_cbz(title, path, download_dir, magazine_name):
    # 定义允许的图片扩展名
    allowed_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}

    # 构建目录路径并过滤图片文件
    directory = Path(path) / download_dir
    paths = sorted(
        (p for p in directory.iterdir()
         if p.is_file() and p.suffix.lower() in allowed_extensions),
        key=lambda x: x.name  # 按文件名自然排序
    )
    pages = [
        PageInfo.load(
            path=path,
            type=PageType.FRONT_COVER if i == 0 else PageType.STORY
        )
        for i, path in enumerate(paths)
    ]
    names = {
        "Kirara": 'まんがタイムきらら',
        "Max": 'まんがタイムきららMAX',
        "Carat": 'まんがタイムきららキャラット',
        "Forward": 'まんがタイムきららフォワード'
    }
    comic = ComicInfo.from_pages(
        pages=pages,
        title=title,
        series=names.get(magazine_name),
        language_iso='ja',
        format=Format.WEB_COMIC,
        black_white=YesNo.NO,
        manga=Manga.YES,
        age_rating=AgeRating.PENDING
    )
    cbz_content = comic.pack()
    if not os.path.exists(path):
        os.makedirs(path)
    cbz_path = Path(f'{path}/{magazine_name}/{title}.cbz')
    cbz_path.write_bytes(cbz_content)
