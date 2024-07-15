import getpass
import json
import os
import re
import time
from os.path import basename
from queue import Queue
from threading import Thread
from zipfile import ZipFile

import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from google.protobuf import json_format
from rich import print
from rich.console import Console
from rich.progress import track

import fuz_pb2

console = Console()

COOKIE = "is_logged_in=true; fuz_session_key="
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 "
              "Safari/537.36 Edg/126.0.0.0")

API_HOST = "https://api.comic-fuz.com"
IMG_HOST = "https://img.comic-fuz.com"
TABLE = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-_"
T_MAP = {s: i for i, s in enumerate(TABLE)}
PROXY = {}


def main(output_dir, user_email, password, token_file, proxy, magazine, compress):
    global PROXY
    # 添加代理
    if proxy:
        PROXY = {'http': f'http://{proxy}', 'https': f'http://{proxy}'}
    print(
        "[white]= [#f9487d]ComicFuz-Extractor [#00BFFF]made with [red]:red_heart-emoji: [#00BFFF]by EnkanRec Repaired "
        "[white]and [#00BFFF]Modified and repair by misaka10843[white]=")
    os.makedirs(output_dir, exist_ok=True)

    token = get_session(token_file, user_email, password)
    get_store_index(token)
    que = Queue(4)
    Thread(target=worker, args=(que,), daemon=True).start()
    downloaded_path = ""
    if ',' in magazine:
        string_list = magazine.split(',')
        for item in string_list:
            downloaded_path = down_magazine(output_dir, int(item), token, que)
            print(f"[bold green]正在等待10s后继续下载")
            time.sleep(10)
    else:
        downloaded_path = down_magazine(output_dir, int(magazine), token, que)
    if compress:
        compression(downloaded_path, output_dir)
    print(f"[bold green]全部任务已完成！")


def sign(email: str, password: str) -> str:
    body = fuz_pb2.SignInRequest()
    body.deviceInfo.deviceType = fuz_pb2.DeviceInfo.DeviceType.BROWSER
    body.email = email
    body.password = password
    url = API_HOST + "/v1/sign_in"
    try:
        response = requests.post(url, data=body.SerializeToString(), proxies=PROXY)
        res = fuz_pb2.SignInResponse()
        res.ParseFromString(response.content)
        if not res.success:
            print(f"[bold red]登录失败,请检查您的账号密码是否准确无误")
            exit(1)
        for header in response.headers:
            m = re.match(r'fuz_session_key=(\w+)(;.*)?', response.headers[header])
            if m:
                return m.group(1)
    except Exception:
        console.print_exception(show_locals=True)
        exit()


def check_sign(token: str) -> bool:
    url = API_HOST + "/v1/web_mypage"
    headers = {
        "user-agent": USER_AGENT,
        "cookie": COOKIE + token
    }
    try:
        response = requests.post(url, headers=headers, proxies=PROXY)
        res = fuz_pb2.WebMypageResponse()
        res.ParseFromString(response.content)
        if res.mailAddress:
            print(f"[#FFB6C1]Login as: {res.mailAddress}")
            return True
        return False
    except Exception:
        console.print_exception(show_locals=True)
        exit()


def get_session(file: str, user: str, pwd: str) -> str:
    if not file and not user:
        print(f"[bold yellow]取消登录,将只能获取免费内容")
        return ""
    if file and os.path.exists(file):
        with open(file) as f:
            token = f.read().strip()
        if check_sign(token):
            return token
        print(f"[bold yellow]获取失败,请重新登录尝试")
    user = user if user else input("您的邮箱: ")
    pwd = pwd if pwd else getpass.getpass("您的密码: ")

    try:
        token = sign(user, pwd)
        if file:
            with open(file, "w") as f:
                f.write(token)
            print(f"[bold green]您的token已经存放到{file}中,请妥善保管")
        return token
    except Exception:
        console.print_exception(show_locals=True)
        console.print(
            "\n[bold yellow]自动获取token出错！\n请如果输出fuz_session_key类似的内容,请从fuz_session_key=开始复制("
            "不包含fuz_session_key=)到第一个分号(;)\n然后存入-t指定的文件中")
        exit()


def b64_to_10(s: str) -> int:
    i = 0
    for c in s:
        i = i * 64 + T_MAP[c]
    return i


def get_index(path: str, body: str, token: str) -> bytes:
    url = API_HOST + path
    headers = {"user-agent": USER_AGENT}
    if token:
        headers["cookie"] = COOKIE + token

    response = requests.post(url, data=body, headers=headers, proxies=PROXY)

    if response.status_code != 200:
        raise Exception("获取相关信息出错！请检查ID参数是否正确！或者稍后重试")

    return response.content


def get_magazine_index(magazine_id: int, token: str) -> fuz_pb2.MagazineViewer2Response:
    body = fuz_pb2.MagazineViewer2Request()
    body.deviceInfo.deviceType = fuz_pb2.DeviceInfo.DeviceType.BROWSER
    body.magazineIssueId = magazine_id
    body.viewerMode.imageQuality = fuz_pb2.ViewerMode.ImageQuality.HIGH

    res = get_index("/v1/magazine_viewer_2", body.SerializeToString(), token)
    index = fuz_pb2.MagazineViewer2Response()
    index.ParseFromString(res)
    return index


def get_store_index(token: str) -> fuz_pb2.BookStorePage:
    body = fuz_pb2.BookStorePageRequest()
    body.deviceInfo.deviceType = fuz_pb2.DeviceInfo.DeviceType.BROWSER

    res = get_index("/v1/store_3", body.SerializeToString(), token)
    index = fuz_pb2.BookStorePage()
    index.ParseFromString(res)
    mid = str(index.info.nested_message3.details.id)
    date = str(index.info.nested_message3.details.updateDate3)
    name = str(index.info.nested_message3.details.magazineName)
    print(mid, date, name)


def download(save_dir: str, image: fuz_pb2.ViewerPage.Image, overwrite=False):
    if not image.imageUrl:
        print(f"[blue]无法获取图片链接,返回内容如下: {image}")
        return
    name = re.match(r'.*/([0-9a-zA-Z_-]+)\.(\w+)\.enc\?.*', image.imageUrl)
    if not name or not name.group(1):
        print(f"[blue]无法检测文件名,返回内容如下: {image}")
        return
    name_num = "%03d" % b64_to_10(name.group(1))
    name = f"{save_dir}{name_num}.{name.group(2)}"
    if not overwrite and os.path.exists(name):
        print(f"图片已有,将跳过此图片,返回内容如下: {name}")
        return
    try:
        data = requests.post(IMG_HOST + image.imageUrl, proxies=PROXY).content
    except Exception:
        time.sleep(5)
        data = requests.post(IMG_HOST + image.imageUrl, proxies=PROXY).content
    key = bytes.fromhex(image.encryptionKey)
    iv = bytes.fromhex(image.iv)
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    out = decryptor.update(data) + decryptor.finalize()
    with open(name, "wb") as f:
        f.write(out)


def down_pages(
        save_dir: str,
        data,
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

    for page in track(data.pages, description=f"[bold yellow]正在下载:{book_name}[/]"):
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
        f"{out_dir}/{magazine_name}/{magazine_name}{has_numbers(str(magazine.magazineIssue.magazineIssueName))}/",
        magazine, que,
        f"[{magazine_name}]{magazine.magazineIssue.magazineIssueName}[/]")
    print(
        f"[bold green]{has_numbers(str(magazine.magazineIssue.magazineIssueName))}下载完成！如果下载时遇见报错,请重新运行一下命令即可")
    return f"{magazine_name}{has_numbers(str(magazine.magazineIssue.magazineIssueName))}"


def has_numbers(chat):
    res_list = [str(int(i)) if i.isdigit() else i for i in chat]
    return "".join(res_list)


def compression(download_dir: str, out_dir: str):
    print("[bold yellow]正在进行压缩中...")
    with console.status(f"[bold yellow]正在将{download_dir}压缩成zip中"):
        file_paths = []
        for root, _, files in os.walk(f'{out_dir}/{download_dir}'):
            for file in files:
                file_path = os.path.join(root, file)
                file_paths.append(file_path)
                break  # 仅遍历当前目录,不进入子目录
        with ZipFile(f'{out_dir}/{download_dir}.zip', 'w') as z:
            for f in files:
                z.write(f, arcname=basename(f))
    print(f"[bold green]已经将图片打包压缩到{out_dir}/{download_dir}.zip")


def worker(que: Queue):
    count = 0
    while True:
        item = que.get()
        count += 1
        item.join()
        que.task_done()


main()
