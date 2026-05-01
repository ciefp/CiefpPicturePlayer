# -*- coding: utf-8 -*-
from __future__ import print_function
import os
import json
import subprocess
import urllib.request
import urllib.parse
import time
import threading
import socket
from ftplib import FTP
from enigma import ePicLoad
from Components.config import config, ConfigSelection, ConfigSubsection, getConfigListEntry
config.plugins.ciefpPicturePlayer = ConfigSubsection()
config.plugins.ciefpPicturePlayer.auto_clear_cache = ConfigSelection(default="500", choices=[
    ("0", "Disabled"),
    ("100", "100 MB"),
    ("500", "500 MB"),
    ("1000", "1 GB"),
    ("2000", "2 GB")
])
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Sources.List import List
from Components.Pixmap import Pixmap
from Screens.Screen import Screen
from Screens.ChoiceBox import ChoiceBox
from Screens.MessageBox import MessageBox
from Screens.VirtualKeyBoard import VirtualKeyBoard
from Components.FileList import FileList
from enigma import eTimer, gFont, eConsoleAppContainer
from Plugins.Plugin import PluginDescriptor
from urllib.parse import unquote

PLUGIN_NAME = "CiefpPicturePlayer"
PLUGIN_DESC = "Picture viewer with local, network and online support"
PLUGIN_VERSION = "1.1"
PLUGIN_DIR = os.path.dirname(__file__) or "/usr/lib/enigma2/python/Plugins/Extensions/CiefpPicturePlayer"

# Mrežni mount point
NETWORK_MOUNT = "/media/network"
os.makedirs(NETWORK_MOUNT, exist_ok=True)

# GitHub TV folder (gde su .tv fajlovi sa slikama)
GITHUB_TV_URL = "https://api.github.com/repos/ciefp/CiefpVibesFiles/contents/Pictures"

# Keš folder
CACHE_DIR = "/tmp/ciefppicture_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def checkAndClearCache():
    limit_mb = int(config.plugins.ciefpPicturePlayer.auto_clear_cache.value)
    if limit_mb == 0:
        return

    if os.path.exists(CACHE_DIR):
        try:
            total_size = 0
            for f in os.listdir(CACHE_DIR):
                fp = os.path.join(CACHE_DIR, f)
                if os.path.isfile(fp):
                    total_size += os.path.getsize(fp)

            if (total_size / (1024 * 1024)) > limit_mb:
                for f in os.listdir(CACHE_DIR):
                    file_path = os.path.join(CACHE_DIR, f)
                    try:
                        if os.path.isfile(file_path):
                            os.unlink(file_path)
                    except:
                        pass
                print("[CiefpPicturePlayer] Cache auto-cleared at {}MB".format(limit_mb))
        except:
            pass

class CiefpPicturePlayer(Screen):
    """Glavni ekran za pregled slika"""

    def buildSkin(self):
        """Kreira skin sa background.png koji se može sakriti"""

        # Kreiraj screen bez background-a u skinu (dodaćemo ga programski)
        return '''<?xml version="1.0" encoding="utf-8"?>
        <screen position="0,0" size="1920,1080" flags="wfNoBorder" backgroundColor="transparent">
            <eLabel position="0,0" size="1920,1080" backgroundColor="#0a1a3a" zPosition="-2"/>

            <eLabel position="0,0" size="640,1080" backgroundColor="#1a2a4a" zPosition="0"/>

            <widget source="content_list" render="Listbox" position="40,100" size="560,800" font="Regular;28" itemHeight="30" valign="center" transparent="1" scrollbarMode="showOnDemand" zPosition="2">
                <convert type="StringList"/>
            </widget>

            <widget name="status" position="40,40" size="560,45" font="Regular;32" foregroundColor="#ffffff" backgroundColor="transparent" transparent="1" zPosition="2"/>

            <widget name="preview" position="700,80" size="1160,740" alphatest="blend" zPosition="2" scale="aspect"/>

            <widget name="time" position="1650,1015" size="200,50" font="Regular;36" halign="right" foregroundColor="#ffffff" backgroundColor="transparent" transparent="1" zPosition="4"/>

            <widget name="key_red"    position="60,1015"  size="250,45" font="Regular;30" foregroundColor="#ff5555" transparent="1" zPosition="3"/>
            <widget name="key_green"  position="350,1015" size="250,45" font="Regular;30" foregroundColor="#55ff55" transparent="1" zPosition="3"/>
            <widget name="key_yellow" position="640,1015" size="250,45" font="Regular;30" foregroundColor="#ffdd55" transparent="1" zPosition="3"/>
            <widget name="key_blue"   position="930,1015" size="250,45" font="Regular;30" foregroundColor="#5599ff" transparent="1" zPosition="3"/>
            <widget name="key_menu"   position="1220,1015" size="250,45" font="Regular;30" foregroundColor="#ffaa55" transparent="1" zPosition="3"/>
        </screen>'''

    def __init__(self, session):
        Screen.__init__(self, session)
        self.session = session

        # Postavi skin
        self.skin = self.buildSkin()
        self.picload = ePicLoad()
        self.picload.PictureData.get().append(self.onPictureLoaded)

        # Widgeti
        self["content_list"] = List([])
        self["preview"] = Pixmap()
        self["status"] = Label("CiefpPicturePlayer v" + PLUGIN_VERSION)
        self["time"] = Label("")
        self["key_red"] = Label("EXIT")
        self["key_green"] = Label("FOLDER")
        self["key_yellow"] = Label("NETWORK")
        self["key_blue"] = Label("ONLINE")
        self["key_menu"] = Label("MENU")

        self.background_widget = None  # Referenca na background widget

        # Podaci
        self.content_items = []
        self.current_path = "/"
        self.current_mode = "local"
        self.preview_timer = eTimer()
        self.preview_timer.callback.append(self.updatePreview)
        self.preview_timer.start(300, False)

        # Time update
        self.time_timer = eTimer()
        self.time_timer.callback.append(self.updateTime)
        self.time_timer.start(1000)

        # Kontejner za komande
        self.container = eConsoleAppContainer()

        # Akcije
        self["actions"] = ActionMap(["ColorActions", "WizardActions", "DirectionActions", "MenuActions"], {
            "ok": self.onOk,
            "back": self.exit,
            "up": self.up,
            "down": self.down,
            "red": self.exit,
            "green": self.openFileBrowser,
            "yellow": self.openNetworkMenu,
            "blue": self.openGitHubLists,
            "menu": self.openSettings,
        }, -1)

        self.onLayoutFinish.append(self.loadLocalContent)

    def updateTime(self):
        try:
            import time
            t = time.strftime("%H:%M:%S")
            self["time"].setText(t)
        except:
            pass

    # DODAJ OVO OVDE (POSLE updateTime, PRE up metode):
    def getCacheSize(self):
        """Vraća veličinu keš foldera u MB"""
        try:
            total_size = 0
            for dirpath, dirnames, filenames in os.walk(CACHE_DIR):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    if os.path.isfile(fp):
                        total_size += os.path.getsize(fp)
            return round(total_size / (1024 * 1024), 1)
        except:
            return 0

    def clearCache(self):
        """Briše sve fajlove u keš folderu"""
        try:
            count = 0
            for filename in os.listdir(CACHE_DIR):
                file_path = os.path.join(CACHE_DIR, filename)
                try:
                    if os.path.isfile(file_path):
                        os.unlink(file_path)
                        count += 1
                except Exception as e:
                    print(f"[CiefpPicturePlayer] Error: {e}")
            return True, count
        except Exception as e:
            print(f"[CiefpPicturePlayer] Error: {e}")
            return False, 0

    def openSettings(self):
        """Otvara Settings meni na MENU dugme"""
        cache_size = self.getCacheSize()

        self.session.openWithCallback(
            self.settingsSelected,
            ChoiceBox,
            title=f"⚙️ Settings • Cache: {cache_size} MB",
            list=[
                ("🗑️ Clear Image Cache", "clear_cache"),
                ("ℹ️ Cache Info", "cache_info"),
                ("⚙️ Set Auto-Limit: {} MB".format(config.plugins.ciefpPicturePlayer.auto_clear_cache.value),
                 "set_limit"),
                ("🌐 Language / Jezik", "language"),
                ("🎨 Theme / Tema", "theme"),
            ]
        )

    def settingsSelected(self, choice):
        if not choice:
            return

        action = choice[1]
        if action == "clear_cache":
            self.confirmClearCache()
        elif action == "cache_info":
            self.showCacheInfo()
        elif action == "set_limit":
            self.changeCacheLimit()
        elif action == "language":
            self.showLanguageMenu()
        elif action == "theme":
            self.showThemeMenu()

    def confirmClearCache(self):
        cache_size = self.getCacheSize()
        self.session.openWithCallback(
            self.clearCacheConfirmed,
            MessageBox,
            f"🗑️ Clear image cache?\n\nCurrent cache size: {cache_size} MB\n\nThis will delete all downloaded images.",
            MessageBox.TYPE_YESNO
        )

    def clearCacheConfirmed(self, result):
        if result:
            success, count = self.clearCache()
            if success:
                self.session.open(MessageBox, f"✅ Cache cleared!\n\n{count} files deleted.", MessageBox.TYPE_INFO,
                                  timeout=2)
                self["status"].setText(f"Cache cleared • {count} files")
            else:
                self.session.open(MessageBox, "❌ Error clearing cache!", MessageBox.TYPE_ERROR)

    def showCacheInfo(self):
        try:
            file_count = len(os.listdir(CACHE_DIR))
        except:
            file_count = 0
        cache_size = self.getCacheSize()

        info = "📁 Cache folder: {}\n".format(CACHE_DIR)
        info += "📄 Files: {}\n".format(file_count)
        info += "💾 Size: {} MB\n\n".format(cache_size)

        # DODATO UPOZORENJE
        if cache_size > 400:
            info += "⚠️ WARNING: Cache is getting full!\n"
            info += "Slideshow might freeze if memory runs out.\n\n"

        info += "🗑️ Cache is cleared automatically when Enigma2 restarts.\n"
        info += "🌐 Online and Phone images are cached for faster viewing."

        self.session.open(MessageBox, info, MessageBox.TYPE_INFO, timeout=10)

    def showLanguageMenu(self):
        """Meni za izbor jezika (placeholder - možeš proširiti)"""
        self.session.openWithCallback(
            self.languageSelected,
            ChoiceBox,
            title="🌐 Select Language / Izaberite jezik",
            list=[
                ("🇬🇧 English", "en"),
                ("🇷🇸 Serbian / Српски", "sr"),
                ("🇩🇪 Deutsch", "de"),
            ]
        )

    def languageSelected(self, choice):
        if choice:
            lang = choice[1]
            # Ovde dodaj logiku za promenu jezika
            # Za sada samo prikaži poruku
            self.session.open(MessageBox,
                              f"🌐 Language changed to: {choice[0]}\n\n(Full translation will be added later)",
                              MessageBox.TYPE_INFO, timeout=2)

    def showThemeMenu(self):
        """Meni za izbor teme (placeholder)"""
        self.session.openWithCallback(
            self.themeSelected,
            ChoiceBox,
            title="🎨 Select Theme / Izaberite temu",
            list=[
                ("🌙 Dark Blue (Default)", "dark_blue"),
                ("🔵 Light Blue", "light_blue"),
                ("⚫ Dark", "dark"),
            ]
        )

    def themeSelected(self, choice):
        if choice:
            # Ovde dodaj logiku za promenu teme
            self.session.open(MessageBox, f"🎨 Theme changed to: {choice[0]}\n\n(Restart plugin to apply changes)",
                              MessageBox.TYPE_INFO, timeout=2)

    def changeCacheLimit(self):
        # Ručno definišemo listu opcija koju smo postavili u config-u
        cache_options = [
            ("0", "Disabled"),
            ("100", "100 MB"),
            ("500", "500 MB"),
            ("1000", "1 GB"),
            ("2000", "2 GB")
        ]

        self.session.openWithCallback(
            self.limitChanged,
            ChoiceBox,
            title="Select Cache Limit",
            list=cache_options
        )

    def limitChanged(self, choice):
        if choice:
            config.plugins.ciefpPicturePlayer.auto_clear_cache.value = choice[0]
            config.plugins.ciefpPicturePlayer.save()
            self.session.open(MessageBox, "Auto-clear limit set to: {} MB".format(choice[0]), MessageBox.TYPE_INFO,
                              timeout=2)

    def up(self):
        self["content_list"].selectPrevious()
        self.preview_timer.start(300, True)

    def down(self):
        self["content_list"].selectNext()
        self.preview_timer.start(300, True)

    def showBackground(self, show=True):
        """Prikaže ili sakrije background.png"""
        if self.background_widget is not None:
            if show:
                self.background_widget.show()
            else:
                self.background_widget.hide()
        else:
            # Prvi put - kreiraj background widget
            bg_path = os.path.join(PLUGIN_DIR, "backgrounds/background.png")
            if os.path.exists(bg_path):
                from enigma import ePixmap
                from enigma import ePoint, eSize
                # ePixmap zahteva parent - koristi self.instance
                self.background_widget = ePixmap(self.instance)
                self.background_widget.setPixmapFromFile(bg_path)
                # Ispravka: move i resize primaju ePoint i eSize
                self.background_widget.move(ePoint(640, 0))
                self.background_widget.resize(eSize(1280, 1080))
                self.background_widget.show()

    def showDefaultBackground(self):
        """Prikaže default pozadinu (tamno plavu) kada nema slike"""
        self.showBackground(True)

    def hideBackgroundForPreview(self):
        """Sakrije background kada se prikazuje preview slike"""
        if self.content_items and len([i for i in self.content_items if i["type"] == "image"]) > 0:
            # Ima slika u listi, sakrij background
            self.showBackground(False)
        else:
            # Nema slika, prikaži background
            self.showBackground(True)

    def onPictureLoaded(self, picInfo=None):
        ptr = self.picload.getData()
        if ptr is not None:
            self["preview"].instance.setPixmap(ptr)
            self["preview"].show()

    def updatePreview(self):
        checkAndClearCache() # DODATO
        idx = self["content_list"].index
        if 0 <= idx < len(self.content_items):
            item = self.content_items[idx]
            if item["type"] == "image":
                # Definisanje varijable na samom početku
                image_path = item.get("path", "")

                # Provera da li putanja uopšte postoji
                if not image_path:
                    self["preview"].hide()
                    self.showBackground(True)
                    return

                # Ako je URL (HTTP ili FTP) → skini ga u cache
                if image_path.startswith("http") or image_path.startswith("ftp"):
                    try:
                        # Čišćenje naziva fajla od URL parametara
                        base_name = os.path.basename(image_path.split("?")[0])
                        filename = os.path.join(CACHE_DIR, base_name)

                        # urllib.request će automatski koristiti kredencijale iz URL-a
                        urllib.request.urlretrieve(image_path, filename)
                        image_path = filename
                    except Exception as e:
                        print("[CiefpPicturePlayer] Download error:", e)
                        self["preview"].hide()
                        self.showBackground(True)
                        return

                # Prikaz slike ako fajl postoji na disku (lokalno ili u cache-u)
                if os.path.exists(image_path):
                    try:
                        self.showBackground(False)
                        self.picload.setPara((1160, 740, 1, 1, False, 1, "#00000000"))
                        self.picload.startDecode(image_path)
                        return
                    except Exception as e:
                        print("[CiefpPicturePlayer] Preview error:", e)

        # Ako ništa od gore navedenog ne prođe, sakrij preview i vrati pozadinu
        self["preview"].hide()
        self.showBackground(True)

    def onOk(self):
        idx = self["content_list"].index
        if 0 <= idx < len(self.content_items):
            item = self.content_items[idx]
            if item["type"] == "folder":
                self.loadFolderContent(item["path"])
            elif item["type"] == "ftp_folder":  # DODATO
                self.loadPhoneFTPContent(item["path"])
            elif item["type"] == "image":
                self.viewFullscreen(item["path"], item["name"])

    def viewFullscreen(self, image_path, image_name):
        """Prikaz preko celog ekrana - skaliranje prepušteno Enigma2"""
        from Screens.Screen import Screen

        class FullscreenViewer(Screen):
            def __init__(self, session, image_list, current_idx):
                Screen.__init__(self, session)
                self.session = session
                self.image_list = image_list
                self.current_idx = current_idx
                self.slideshow_active = False
                self.slideshow_timer = eTimer()
                self.slideshow_timer.callback.append(self.nextImage)
                self.picload = ePicLoad()
                self.picload.PictureData.get().append(self.onPictureLoaded)

                self.skin = '''
                <screen position="0,0" size="1920,1080" flags="wfNoBorder" backgroundColor="black">
                    <!-- Centriranje slike -->
                    <widget name="image" position="0,0" size="1920,1080" alphatest="on" scale="aspect"/>
                    <widget name="filename" position="60,980" size="1800,50" font="Regular;32" foregroundColor="#ffffff" transparent="1" halign="center"/>
                    <widget name="key_red" position="60,1030" size="260,50" font="Regular;30" foregroundColor="#ff5555" transparent="1"/>
                    <widget name="key_green" position="350,1030" size="260,50" font="Regular;30" foregroundColor="#55ff55" transparent="1"/>
                    <widget name="key_blue" position="980,1030" size="260,50" font="Regular;30" foregroundColor="#5599ff" transparent="1"/>
                </screen>'''

                self["image"] = Pixmap()
                self["filename"] = Label("")
                self["key_red"] = Label("BACK")
                self["key_green"] = Label("SLIDESHOW")
                self["key_blue"] = Label("INFO")

                self["actions"] = ActionMap(["ColorActions", "DirectionActions"], {
                    "red": self.goBack,
                    "green": self.toggleSlideshow,
                    "blue": self.showInfo,
                    "left": self.prevImage,
                    "right": self.nextImage,
                }, -1)

                self.onLayoutFinish.append(self.displayImage)

            def goBack(self):
                self.close()

            def displayImage(self):
                checkAndClearCache() # DODATO
                if 0 <= self.current_idx < len(self.image_list):
                    item = self.image_list[self.current_idx]
                    path = item.get("path", "")
                    name = item.get("name", "Unknown")

                    self["filename"].setText(name)

                    try:
                        if path.startswith("http") or path.startswith("ftp"):
                            try:
                                base_name = os.path.basename(path.split("?")[0])
                                filename = os.path.join(CACHE_DIR, base_name)

                                if not os.path.exists(filename):
                                    import urllib.request

                                    # RUČNA PROVERA KEŠA (pošto self.getCacheSize ovde ne radi)
                                    try:
                                        total_size = 0
                                        for f in os.listdir(CACHE_DIR):
                                            fp = os.path.join(CACHE_DIR, f)
                                            if os.path.isfile(fp):
                                                total_size += os.path.getsize(fp)

                                        if (total_size / (1024 * 1024)) > 500:
                                            # RUČNO BRISANJE
                                            for f in os.listdir(CACHE_DIR):
                                                os.unlink(os.path.join(CACHE_DIR, f))
                                    except:
                                        pass

                                    urllib.request.urlretrieve(path, filename)
                                path = filename

                            except Exception as e:
                                print("[Fullscreen Download Error]:", e)
                                self["filename"].setText("Download error: " + name)
                                return

                        if os.path.exists(path):
                            self.picload.setPara((1920, 1080, 1, 1, False, 1, "#00000000"))
                            self.picload.startDecode(path)
                        else:
                            self["filename"].setText("File not found: " + name)

                    except Exception as e:
                        self["filename"].setText("Error: " + str(e))
                        print("[Fullscreen] Critical Error:", e)

            def onPictureLoaded(self, picInfo=None):
                ptr = self.picload.getData()
                if ptr is not None:
                    self["image"].instance.setPixmap(ptr)

            def toggleSlideshow(self):
                if self.slideshow_active:
                    self.slideshow_timer.stop()
                    self.slideshow_active = False
                    self["key_green"].setText("SLIDESHOW")
                else:
                    self.slideshow_timer.start(5000, False)
                    self.slideshow_active = True
                    self["key_green"].setText("STOP")

            def nextImage(self):
                if self.current_idx + 1 < len(self.image_list):
                    self.current_idx += 1
                    self.displayImage()
                    if self.slideshow_active:
                        self.slideshow_timer.start(5000, True)

            def prevImage(self):
                if self.current_idx > 0:
                    self.current_idx -= 1
                    self.displayImage()
                    if self.slideshow_active:
                        self.slideshow_timer.start(5000, True)

            def showInfo(self):
                if 0 <= self.current_idx < len(self.image_list):
                    path = self.image_list[self.current_idx]["path"]
                    try:
                        size = os.path.getsize(path)
                        size_mb = size / (1024 * 1024)
                        self.session.open(MessageBox,
                                          "Size: {:.1f} MB\nPosition: {}/{}".format(size_mb, self.current_idx + 1,
                                                                                    len(self.image_list)),
                                          MessageBox.TYPE_INFO, timeout=2)
                    except:
                        pass

        # Prikupi sve slike
        images = [item for item in self.content_items if item["type"] == "image"]
        current_idx = 0
        for i, img in enumerate(images):
            if img["path"] == image_path:
                current_idx = i
                break

        if images:
            self.session.open(FullscreenViewer, images, current_idx)

    # === LOKALNI SADRŽAJ (kao u CiefpVibes) ===
    
    def loadLocalContent(self):
        self.current_mode = "local"
        self.current_path = "/"
        self["status"].setText("Local - Press GREEN for folder browser")
        self.loadFolderContent("/")

    def loadFolderContent(self, folder_path):
        if not os.path.isdir(folder_path):
            self["status"].setText("Path not found: " + str(folder_path))
            return

        self.current_path = folder_path
        self.content_items = []

        # Lista ekstenzija - samo mala slova
        image_extensions = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")

        # Parent folder
        if folder_path != "/":
            parent = os.path.dirname(folder_path.rstrip('/'))
            if not parent:
                parent = "/"
            self.content_items.append({
                "name": ".. (Up)",
                "path": parent,
                "type": "folder",
                "info": ""
            })

        try:
            items = os.listdir(folder_path)
            folders = []
            images = []

            for item in sorted(items, key=str.lower):
                if item.startswith('.'):
                    continue
                full_path = os.path.join(folder_path, item)

                if os.path.isdir(full_path):
                    folders.append({
                        "name": "[DIR] " + item,
                        "path": full_path,
                        "type": "folder",
                        "info": ""
                    })
                else:
                    # KLJUČNA RAZLIKA: koristi os.path.splitext
                    ext = os.path.splitext(item)[1].lower().strip()
                    if ext in image_extensions:
                        try:
                            size = os.path.getsize(full_path)
                            size_kb = size / 1024
                            if size_kb > 1024:
                                info = "{:.1f}MB".format(size_kb / 1024)
                            else:
                                info = "{:.0f}KB".format(size_kb)
                        except:
                            info = ""

                        images.append({
                            "name": item,  # Originalno ime (zadržava velika slova)
                            "path": full_path,
                            "type": "image",
                            "info": info
                        })

            self.content_items.extend(folders)
            self.content_items.extend(images)
            self.updateContentList()

            self.hideBackgroundForPreview()

            self["status"].setText("{} | {} images, {} folders".format(folder_path, len(images), len(folders)))

        except Exception as e:
            print("[CiefpPicturePlayer] Error:", str(e))
            self["status"].setText("Error reading folder")

    def updateContentList(self):
        print("[DEBUG] updateContentList called, items:", len(self.content_items))
        list_data = []
        for item in self.content_items:
            if item["info"]:
                display = "{} [{}]".format(item["name"], item["info"])
            else:
                display = item["name"]
            list_data.append(display)
            print("[DEBUG] Adding to list:", display)  # DODAJ OVO

        print("[DEBUG] Setting list with", len(list_data), "items")
        self["content_list"].setList(list_data)

    def openFileBrowser(self):
        """Otvori file browser (kao u CiefpVibes)"""
        from Screens.ChoiceBox import ChoiceBox
        
        self.session.openWithCallback(
            self.browserTypeSelected,
            ChoiceBox,
            title="Select Source",
            list=[
                ("Local Storage", "local"),
                ("Network (Laptop)", "network"),
            ]
        )
    
    def browserTypeSelected(self, choice):
        if not choice:
            return
        
        if choice[1] == "local":
            self.session.openWithCallback(
                self.localLocationSelected,
                ChoiceBox,
                title="Local Storage",
                list=[
                    ("Media/HDD", "/media/hdd"),
                    ("USB", "/media/usb"),
                    ("Root", "/"),
                    ("Home", "/home/root"),
                    ("TMP", "/tmp"),
                ]
            )
        elif choice[1] == "network":
            self.openNetworkMenu()
    
    def localLocationSelected(self, choice):
        if choice:
            self.session.openWithCallback(
                self.fileBrowserClosed,
                CiefpFileBrowser,
                initial_dir=choice[1]
            )
    
    def fileBrowserClosed(self, result):
        if result:
            filepath, display_name = result
            if os.path.isdir(filepath):
                self.loadFolderContent(filepath)
    
    # === MREŽNI SADRŽAJ (kopirano iz CiefpVibes) ===
    def openNetworkMenu(self):
        from Screens.ChoiceBox import ChoiceBox

        self.session.openWithCallback(
            self.networkMenuSelected,
            ChoiceBox,
            title="Network Options",
            list=[
                ("Connect to Phone (Android FTP)", "connect_phone_ftp"),  # DODATO
                ("Connect to Laptop (SMB)", "connect_laptop"),
                ("Browse Network Shares", "browse_network"),
                ("Add Network Share", "add_share"),
                ("Disconnect All", "disconnect"),
                ("Auto-Scan", "autoscan"),
            ]
        )

    def networkMenuSelected(self, choice):
        if not choice:
            return

        if choice[1] == "connect_phone_ftp":
            # Prvo unosimo IP adresu
            self.session.openWithCallback(
                self.phoneIPEntered,
                VirtualKeyBoard,
                title="Enter Phone IP Address",
                text="192.168.1."
            )

        elif choice[1] == "connect_laptop":
            self.connectToLaptop()
        elif choice[1] == "browse_network":
            self.browseNetworkShares()
        elif choice[1] == "add_share":
            self.addNetworkShare()
        elif choice[1] == "disconnect":
            self.disconnectNetwork()
        elif choice[1] == "autoscan":
            self.autoScanNetwork()

    def phoneIPEntered(self, ip_address):
        if not ip_address: return
        self.phone_ip = ip_address
        self.session.openWithCallback(
            self.phonePortEntered,
            VirtualKeyBoard,
            title="Enter FTP Port",
            text="2121"
        )

    def phonePortEntered(self, port):
        if not port: return
        self.phone_port = port
        self.session.openWithCallback(
            self.phoneUserEntered,
            VirtualKeyBoard,
            title="Enter FTP Username (Leave empty for anonymous)",
            text="root"
        )

    def phoneUserEntered(self, user):
        # Ako je prazno, postavi na 'anonymous'
        self.phone_user = user if user else "anonymous"
        self.session.openWithCallback(
            self.phonePassEntered,
            VirtualKeyBoard,
            title="Enter FTP Password",
            text=""
        )

    def phonePassEntered(self, password):
        self.phone_pass = password
        # Sada imamo sve podatke, pokrećemo učitavanje
        self.loadPhoneFTPContent("/")

    def loadPhoneFTPContent(self, remote_path):
        self["status"].setText("Connecting to {}:{}...".format(self.phone_ip, self.phone_port))
        try:
            from ftplib import FTP
            ftp = FTP()
            ftp.connect(self.phone_ip, int(self.phone_port), timeout=8)
            ftp.login(self.phone_user, self.phone_pass)
            ftp.set_pasv(True)
            ftp.cwd(remote_path)

            self.current_path = remote_path
            self.content_items = []
            image_extensions = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")

            # Logika za povratak nazad (Up) - MORA biti prvi u self.content_items
            if remote_path != "/":
                parent = os.path.dirname(remote_path.rstrip('/')) or "/"
                self.content_items.append({
                    "name": ".. (Up)",
                    "path": parent,
                    "type": "ftp_folder",
                    "info": ""
                })

            listing = []
            ftp.retrlines('LIST', listing.append)

            folders = []
            images = []

            for line in listing:
                parts = line.split(None, 8)
                if len(parts) < 9: continue
                name = parts[8].strip()
                if name in (".", ".."): continue

                is_dir = parts[0].startswith('d')
                # Ručno pravimo putanju da izbegnemo probleme sa os.path.join na FTP-u
                if remote_path.endswith('/'):
                    full_path = remote_path + name
                else:
                    full_path = remote_path + '/' + name

                if is_dir:
                    folders.append({
                        "name": "[DIR] " + name,
                        "path": full_path,
                        "type": "ftp_folder",
                        "info": ""
                    })
                else:
                    ext = os.path.splitext(name)[1].lower()
                    if ext in image_extensions:
                        url = "ftp://{}:{}@{}:{}{}".format(
                            self.phone_user,
                            self.phone_pass,
                            self.phone_ip,
                            self.phone_port,
                            full_path
                        )
                        images.append({
                            "name": name,
                            "path": url,
                            "type": "image",
                            "info": "Phone"
                        })

            # SORTIRANJE:
            # Sortiramo foldere po imenu (bez [DIR] prefiksa u poređenju)
            folders.sort(key=lambda x: str(x["name"]).lower())

            # Sortiramo slike od najnovije ka starijoj (važno za IMG_YYYYMMDD...)
            images.sort(key=lambda x: str(x["name"]), reverse=True)

            # SPAJANJE:
            # self.content_items već sadrži ".. (Up)" ako nismo u root-u
            self.content_items.extend(folders)
            self.content_items.extend(images)

            self.updateContentList()
            self.current_mode = "phone_ftp"
            self["status"].setText("Phone FTP: " + remote_path)
            ftp.quit()

        except Exception as e:
            self.session.open(MessageBox, "FTP Login Failed: " + str(e), MessageBox.TYPE_ERROR)
            self["status"].setText("Connection Error")

    def connectToLaptop(self):
        from Screens.VirtualKeyBoard import VirtualKeyBoard
        
        self.session.openWithCallback(
            self.laptopIPEntered,
            VirtualKeyBoard,
            title="Enter Laptop IP Address",
            text="192.168.1."
        )
    
    def laptopIPEntered(self, ip_address):
        if not ip_address:
            return
        
        self.session.openWithCallback(
            lambda share_name: self.mountLaptopShare(ip_address, share_name),
            VirtualKeyBoard,
            title="Enter Share Name (or leave empty for default)",
            text=""
        )

    def mountLaptopShare(self, ip_address, share_name=""):
        mount_point = os.path.join(NETWORK_MOUNT, "laptop")
        os.makedirs(mount_point, exist_ok=True)

        if share_name:
            smb_path = "//{}/{}".format(ip_address, share_name)
        else:
            smb_path = "//{}".format(ip_address)

        self["status"].setText("Connecting to {}...".format(ip_address))

        if self.mountSMBShare(smb_path, mount_point):
            # Prikaži poruku
            msg = self.session.open(MessageBox, "Successfully connected!", MessageBox.TYPE_INFO, timeout=3)
            self.loadFolderContent(mount_point)
        else:
            self.session.open(MessageBox, "Cannot connect! Check IP and sharing.", MessageBox.TYPE_ERROR)
            self["status"].setText("Connection failed")

    def mountSMBShare(self, smb_path, mount_point):
        try:
            if os.path.ismount(mount_point):
                subprocess.run(["umount", "-l", mount_point], capture_output=True)
            
            cmd = ["mount", "-t", "cifs", smb_path, mount_point, "-o", "ro,guest,iocharset=utf8"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                print("[CiefpPicturePlayer] SMB mount successful")
                return True
            else:
                cmd2 = ["mount", "-t", "cifs", smb_path, mount_point, "-o", "ro,user=guest,password="]
                result2 = subprocess.run(cmd2, capture_output=True, text=True)
                return result2.returncode == 0
        except Exception as e:
            print("[CiefpPicturePlayer] Mount error:", e)
            return False
    
    def browseNetworkShares(self):
        mounted_shares = []
        try:
            with open("/proc/mounts", "r") as f:
                for line in f:
                    if "cifs" in line or NETWORK_MOUNT in line:
                        parts = line.split()
                        if len(parts) >= 2:
                            mounted_shares.append(parts[1])
        except:
            pass
        
        if mounted_shares:
            choices = [("📂 " + share, share) for share in mounted_shares]
            choices.append(("➕ Add New Share", "add_new"))
            
            self.session.openWithCallback(
                self.shareSelected,
                ChoiceBox,
                title="Network Shares",
                list=choices
            )
        else:
            self.session.open(MessageBox, "No network shares found!", MessageBox.TYPE_INFO)
            self.connectToLaptop()
    
    def shareSelected(self, choice):
        if not choice:
            return
        
        if choice[1] == "add_new":
            self.connectToLaptop()
        else:
            self.loadFolderContent(choice[1])
    
    def addNetworkShare(self):
        from Screens.ChoiceBox import ChoiceBox
        
        self.session.openWithCallback(
            self.shareTypeSelected,
            ChoiceBox,
            title="Add Network Share",
            list=[
                ("Windows SMB/CIFS", "smb"),
                ("Linux NFS", "nfs"),
            ]
        )
    
    def shareTypeSelected(self, choice):
        if not choice:
            return
        
        share_type = choice[1]
        self.session.openWithCallback(
            lambda details: self.configureShare(share_type, details),
            VirtualKeyBoard,
            title="Enter {} path".format(share_type.upper()),
            text="192.168.1.100/Photos"
        )
    
    def configureShare(self, share_type, path):
        if not path:
            return
        
        mount_name = path.replace("/", "_").replace(".", "_")
        mount_point = os.path.join(NETWORK_MOUNT, mount_name)
        os.makedirs(mount_point, exist_ok=True)
        
        if share_type == "smb":
            success = self.mountSMBShare("//" + path, mount_point)
        elif share_type == "nfs":
            cmd = ["mount", "-t", "nfs", path, mount_point, "-o", "ro"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            success = result.returncode == 0
        else:
            return
        
        if success:
            self.session.open(MessageBox, "Share mounted!", MessageBox.TYPE_INFO)
            self.loadFolderContent(mount_point)
    
    def disconnectNetwork(self):
        try:
            for item in os.listdir(NETWORK_MOUNT):
                mount_point = os.path.join(NETWORK_MOUNT, item)
                if os.path.ismount(mount_point):
                    subprocess.run(["umount", "-l", mount_point], capture_output=True)
            self.session.open(MessageBox, "All network shares disconnected", MessageBox.TYPE_INFO)
            self.loadLocalContent()
        except Exception as e:
            print("[CiefpPicturePlayer] Unmount error:", e)
    
    def autoScanNetwork(self):
        import socket
        import threading
        
        self["status"].setText("Scanning network for SMB shares...")
        
        def scan_job():
            found_devices = []
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                my_ip = s.getsockname()[0]
                s.close()
                base_ip = ".".join(my_ip.split(".")[:3]) + "."
            except:
                base_ip = "192.168.1."
            
            for i in range(1, 255):
                ip = base_ip + str(i)
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(0.3)
                    result = sock.connect_ex((ip, 445))
                    if result == 0:
                        try:
                            hostname = socket.gethostbyaddr(ip)[0]
                        except:
                            hostname = ip
                        found_devices.append((hostname, ip))
                    sock.close()
                except:
                    pass
            
            if found_devices:
                choices = [("{} ({})".format(hostname, ip), ip) for hostname, ip in found_devices]
                self.session.openWithCallback(
                    self.scannedDeviceSelected,
                    ChoiceBox,
                    title="Found Devices",
                    list=choices
                )
            else:
                self.session.open(MessageBox, "No SMB devices found!", MessageBox.TYPE_INFO)
            
            self["status"].setText("Ready")
        
        thread = threading.Thread(target=scan_job)
        thread.daemon = True
        thread.start()
    
    def scannedDeviceSelected(self, choice):
        if choice:
            self.laptopIPEntered(choice[1])
    
    # === ONLINE SADRŽAJ (kao u CiefpVibes) ===
    
    def openGitHubLists(self):
        """Otvara listu .tv fajlova sa GitHub-a (kao u CiefpVibes)"""
        self.session.openWithCallback(
            self.githubCategorySelected,
            ChoiceBox,
            title="Online Files",
            list=[
                ("TV Bouquets (Picture lists)", "TV"),
            ]
        )
    
    def githubCategorySelected(self, choice):
        if not choice:
            return
        
        cat = choice[1]
        if cat == "TV":
            url = GITHUB_TV_URL
        
        items = self.fetchGitHubLists(url, cat)
        if not items:
            self.session.open(MessageBox, "No lists in {} category.".format(cat), MessageBox.TYPE_INFO)
            return
        
        self.session.openWithCallback(
            self.githubListSelected,
            ChoiceBox,
            title="Choose {} list".format(cat),
            list=[(display, (dl_url, filename)) for display, dl_url, filename in items]
        )
    
    def fetchGitHubLists(self, url, category):
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "{}/{}".format(PLUGIN_NAME, PLUGIN_VERSION))
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                items = []
                for item in data:
                    if item.get("type") == "file":
                        name = item.get("name", "")
                        dl_url = item.get("download_url")
                        if dl_url and name.lower().endswith((".tv", ".radio")):
                            clean = name
                            if clean.startswith("userbouquet."):
                                clean = clean[12:]
                            clean = clean.replace(".tv", "").replace(".radio", "")
                            clean = clean.replace("_", " ").strip()
                            # Capitalize
                            words = [w.capitalize() for w in clean.split()]
                            display = " ".join(words)
                            items.append((display, dl_url, name))
                return sorted(items, key=lambda x: x[0].lower())
        except Exception as e:
            print("[CiefpPicturePlayer] GitHub error:", e)
            return []
    
    def githubListSelected(self, choice):
        if not choice:
            return
        
        dl_url, filename = choice[1]
        display_name = choice[0]
        
        tmp_path = os.path.join(CACHE_DIR, filename)
        
        try:
            urllib.request.urlretrieve(dl_url, tmp_path)
            print("[CiefpPicturePlayer] Downloaded:", filename)
            
            # Parsiraj .tv fajl i prikaži slike u listi
            self.loadImagesFromBouquet(tmp_path, display_name)
            
        except Exception as e:
            print("[CiefpPicturePlayer] Error:", e)
            self.session.open(MessageBox, "Error:\n{}".format(str(e)[:100]), MessageBox.TYPE_ERROR)

    def loadImagesFromBouquet(self, bouquet_path, display_name):
        """Parsira .tv fajl i izvlači slike (kao parseTVBouquet u CiefpVibes)"""
        try:
            with open(bouquet_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = [line.strip() for line in f.readlines()]
        except Exception as e:
            print("[CiefpPicturePlayer] Error reading bouquet:", e)
            return

        self.content_items = []
        image_count = 0

        i = 0
        while i < len(lines):
            line = lines[i]
            if line.startswith("#SERVICE 4097:"):
                try:
                    parts = line[9:].split(":")
                    if len(parts) >= 11:
                        if len(parts) > 11:
                            url_encoded = ":".join(parts[10:-1])
                            name = parts[-1].strip()
                        else:
                            url_encoded = parts[10]
                            name = None

                        url = unquote(url_encoded).strip()

                        if not name and i + 1 < len(lines) and lines[i + 1].startswith("#DESCRIPTION"):
                            name = lines[i + 1][13:].strip()
                            i += 1

                        name = name or "Unknown"

                        # Provera ekstenzije (case-insensitive)
                        ext = os.path.splitext(url.split('?')[0])[1].lower().strip() if '?' not in url else \
                        os.path.splitext(url.split('?')[0])[1].lower()
                        image_extensions = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")

                        if ext in image_extensions:
                            self.content_items.append({
                                "name": name,  # Zadržava originalni naziv
                                "path": url,
                                "type": "image",
                                "info": "Online"
                            })
                            image_count += 1

                except Exception as ex:
                    print("[CiefpPicturePlayer] Error parsing line:", ex)
            i += 1

        if image_count > 0:
            self.updateContentList()
            self["status"].setText("Online: {} images from {}".format(image_count, display_name))
            self.current_mode = "online"

            # Prikaži prvu sliku ako postoji
            if image_count > 0:
                self["content_list"].index = 0
                self.updatePreview()
        else:
            self.session.open(MessageBox, "No images found in this bouquet!", MessageBox.TYPE_WARNING)
            self["status"].setText("No images in bouquet")

    def exit(self):
        self.close()


# === FILE BROWSER (kao u CiefpVibes) ===
class CiefpFileBrowser(Screen):
    """File browser za odabir foldera"""
    
    skin = '''
    <screen position="center,140" size="1200,700" title="SELECT FOLDER">
        <widget name="filelist" position="10,10" size="1180,600" scrollbarMode="showOnDemand"/>
        <widget name="curr_dir" position="10,630" size="1180,40" font="Regular;28" halign="center"/>
        <widget name="key_red" position="40,660" size="200,50" font="Regular;32" halign="center" foregroundColor="#ff5555"/>
        <widget name="key_green" position="280,660" size="200,50" font="Regular;32" halign="center" foregroundColor="#55ff55"/>
    </screen>
    '''
    
    def __init__(self, session, initial_dir="/"):
        Screen.__init__(self, session)
        self.session = session
        
        self["filelist"] = FileList(initial_dir, showDirectories=True, showFiles=False)
        self["curr_dir"] = Label(initial_dir)
        self["key_red"] = Label("Cancel")
        self["key_green"] = Label("Select")

        self["actions"] = ActionMap(["OkCancelActions", "ColorActions"], {
            "ok": self.enter,
            "cancel": self.cancel,
            "red": self.cancel,
            "green": self.select,
        }, -1)
        
        self.onLayoutFinish.append(self.updateDir)
    
    def updateDir(self):
        self["curr_dir"].setText(self["filelist"].getCurrentDirectory() or "/")

    def enter(self):
        if self["filelist"].canDescent():
            self["filelist"].descent()
            self.updateDir()

    def select(self):
        selected = self["filelist"].getCurrentDirectory()
        if selected:
            self.close((selected, os.path.basename(selected)))

    def cancel(self):
        self.close(None)


# === PLUGIN ENTRY ===
def main(session, **kwargs):
    session.open(CiefpPicturePlayer)

def Plugins(**kwargs):
    return [PluginDescriptor(
        name="{} v{}".format(PLUGIN_NAME, PLUGIN_VERSION),
        description=PLUGIN_DESC,
        where=PluginDescriptor.WHERE_PLUGINMENU,
        icon="plugin.png",
        fnc=main
    )]