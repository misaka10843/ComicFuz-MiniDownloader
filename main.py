#!/usr/bin/env python3
# todo 1. 将urllib更换成requests
# todo 2. 将所有输出切换为logging
# todo 3. 预留参数接口
# todo 4. 调用返回状态以及压缩包路径
import os
import re
import time

import fuz_pb2
import json
import py7zr
import getpass
import logging
from urllib.request import Request, ProxyHandler, build_opener
from google.protobuf import json_format
from threading import Thread
from queue import Queue
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

COOKIE = "is_logged_in=true; fuz_session_key="
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)" \
             " AppleWebKit/537.36 (KHTML, like Gecko)" \
             " Chrome/96.0.4664.55" \
             " Safari/537.36" \
             " Edg/96.0.1054.34"

API_HOST = "https://api.comic-fuz.com"
IMG_HOST = "https://img.comic-fuz.com"
TABLE = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_"
T_MAP = {s: i for i, s in enumerate(TABLE)}

urlopen = build_opener()


def main(proxy, output_dir, token_file, user_email, password, magazine):
    global urlopen
    n_jobs = 16
    # 添加代理
    if proxy:
        proxy_handler = ProxyHandler(
            {'http': f'http://{proxy}', 'https': f'http://{proxy}'})
        urlopen = build_opener(proxy_handler)
    else:
        urlopen = build_opener()
    print(
        "[white]= [#f9487d]ComicFuz-Extractor [#00BFFF]made with [red]:red_heart-emoji: [#00BFFF]by EnkanRec Repaired "
        "[white]and [#00BFFF]Modified and repair by misaka10843[white]=")
    os.makedirs(output_dir, exist_ok=True)

    token = get_session(token_file, user_email, password)
    que = Queue(n_jobs)
    Thread(target=worker, args=(que,), daemon=True).start()
    downloaded_path = down_magazine(output_dir, magazine, token, que)
    compression(downloaded_path, output_dir)
    logging.debug("Done.")


def sign(email: str, password: str) -> str:
    body = fuz_pb2.SignInRequest()
    body.deviceInfo.deviceType = fuz_pb2.DeviceInfo.DeviceType.BROWSER
    body.email = email
    body.password = password
    url = API_HOST + "/v1/sign_in"
    req = Request(url, body.SerializeToString(), method="POST")
    try:
        with urlopen.open(req) as r:
            res = fuz_pb2.SignInResponse()
            res.ParseFromString(r.read())
            if not res.success:
                logging.error("Login failed")
                exit(1)
            for header in r.headers:
                m = re.match(r'fuz_session_key=(\w+)(;.*)?', r.headers[header])
                if m:
                    return m.group(1)
    except Exception as e:
        exit()


def check_sign(token: str) -> bool:
    url = API_HOST + "/v1/web_mypage"
    headers = {
        "user-agent": USER_AGENT,
        "cookie": COOKIE + token
    }
    req = Request(url, headers=headers, method="POST")
    try:
        with urlopen.open(req) as r:
            res = fuz_pb2.WebMypageResponse()
            res.ParseFromString(r.read())
            if res.mailAddress:
                print(f"[#FFB6C1]Login as: {res.mailAddress}")
                return True
            return False
    except Exception as e:
        exit()


def get_session(file: str, user: str, pwd: str) -> str:
    if not file and not user:
        logging.info("Disable login, get only free part.")
        return ""
    if file and os.path.exists(file):
        with open(file) as f:
            token = f.read().strip()
        if check_sign(token):
            return token
        logging.debug("Get failed, try signing")
    user = user if user else input("您的邮箱: ")
    pwd = pwd if pwd else getpass.getpass("您的密码: ")
    token = sign(user, pwd)
    try:
        with open(file, "w") as f:
            f.write(token)
        print(f"[bold green]您的token已经存放到{file}中，请妥善保管")
        return token
    except Exception as e:
        print(
            "\n[bold yellow]自动获取token出错！\n请如果输出fuz_session_key类似的内容，请从fuz_session_key=开始复制("
            "不包含fuz_session_key=)到第一个分号(;)\n然后存入-t指定的文件中")
        exit()


def b64_to_10(s: str) -> int:
    i = 0
    for c in s:
        i = i * 64 + T_MAP[c]
    return i


def get_index(path: str, body: str, token: str) -> str:
    url = API_HOST + path
    headers = {"user-agent": USER_AGENT}
    if token:
        headers["cookie"] = COOKIE + token
    req = Request(url, body, headers, method="POST")
    try:
        with urlopen.open(req) as r:
            return r.read()
    except Exception as e:
        print("\n[bold red]获取相关信息出错！\n请检查ID参数是否正确！\n或者稍后重试")
        exit()


def get_magazine_index(magazine_id: int, token: str) -> fuz_pb2.MagazineViewer2Response:
    body = fuz_pb2.MagazineViewer2Request()
    body.deviceInfo.deviceType = fuz_pb2.DeviceInfo.DeviceType.BROWSER
    body.magazineIssueId = magazine_id
    body.viewerMode.imageQuality = fuz_pb2.ViewerMode.ImageQuality.HIGH

    res = get_index("/v1/magazine_viewer_2", body.SerializeToString(), token)
    index = fuz_pb2.MagazineViewer2Response()
    index.ParseFromString(res)
    return index


def download(save_dir: str, image: fuz_pb2.ViewerPage.Image, overwrite=False):
    if not image.imageUrl:
        logging.debug("Not an image: %s", image)
        return
    name = re.match(r'.*/([0-9a-zA-Z_-]+)\.(\w+)\.enc\?.*', image.imageUrl)
    if not name or not name.group(1):
        logging.debug("Can't gass filename: %s", image)
        return
    name_num = "%03d" % b64_to_10(name.group(1))
    name = f"{save_dir}{name_num}.{name.group(2)}"
    if not overwrite and os.path.exists(name):
        logging.debug("Exists, continue: %s", name)
        return
    try:
        with urlopen.open(IMG_HOST + image.imageUrl) as r:
            data = r.read()
    except Exception as e:
        time.sleep(5)
        with urlopen.open(IMG_HOST + image.imageUrl) as r:
            data = r.read()
    key = bytes.fromhex(image.encryptionKey)
    iv = bytes.fromhex(image.iv)
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    out = decryptor.update(data) + decryptor.finalize()
    with open(name, "wb") as f:
        f.write(out)
    # os.system(f"curl -s \"{IMG_HOST}{image.imageUrl}\" | openssl aes-256-cbc -d -K {image.encryptionKey} -iv {
    # image.iv} -in - -out {name}")
    logging.debug("Downloaded: %s", name)


def down_pages(
        save_dir: str,
        data,  # : fuz_pb2.BookViewer2Response | fuz_pb2.MagazineViewer2Response | fuz_pb2.MangaViewerResponse,
        que: Queue,
        book_name: str
):
    os.makedirs(save_dir, exist_ok=True)
    with open(save_dir + "index.protobuf", "wb") as f:
        f.write(data.SerializeToString())
    with open(save_dir + "index.json", "w", encoding='utf-8') as f:
        json.dump(json_format.MessageToDict(data),
                  f, ensure_ascii=False, indent=4)

    # downloadThumb(save_dir, data.bookIssue.thumbnailUrl)

    for page in data.pages:
        t = Thread(target=download, name=page.image.imageUrl,
                   args=(save_dir, page.image))
        t.start()
        # download(save_dir, page)
        que.put(t)
    que.join()


def down_magazine(out_dir: str, magazine_id: int, token: str, que: Queue):
    magazine = get_magazine_index(magazine_id, token)
    magazine_name = str(magazine.magazineIssue.magazineName)
    if magazine_name == 'まんがタイムきらら':
        magazine_name = "Kirara"
    elif magazine_name == 'まんがタイムきららMAX':
        magazine_name = "Max"
    elif magazine_name == 'まんがタイムきららキャラット':
        magazine_name = "Carat"
    elif magazine_name == 'まんがタイムきららフォワード':
        magazine_name = "Forward"
    down_pages(
        f"{out_dir}/{magazine_name}{has_numbers(str(magazine.magazineIssue.magazineIssueName))}/", magazine, que,
        f"[{magazine_name}]{magazine.magazineIssue.magazineIssueName}[/]")
    print(
        f"[bold green]{has_numbers(str(magazine.magazineIssue.magazineIssueName))}下载完成！如果下载时遇见报错，请重新运行一下命令即可")
    return f"{magazine_name}{has_numbers(str(magazine.magazineIssue.magazineIssueName))}"


def has_numbers(chat):
    res_list = [str(int(i)) if i.isdigit() else i for i in chat]
    return "".join(res_list)


def compression(download_dir: str, out_dir: str):
    print("[bold yellow]正在进行压缩中...")
    with py7zr.SevenZipFile(f'{out_dir}/{download_dir}_og.7z', 'w') as archive:
        archive.writeall(f"{out_dir}/{download_dir}_og")
    print(f"[bold green]已经将原图打包压缩到{out_dir}/{download_dir}_og.7z")


def worker(que: Queue):
    count = 0
    while True:
        item = que.get()
        count += 1
        item.join()
        # logging.debug("[%d] ok.", count)
        que.task_done()
