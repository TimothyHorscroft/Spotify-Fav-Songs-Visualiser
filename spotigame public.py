import json
import spotipy
import statistics
import pygame
import pygame.freetype
import requests
import io
import datetime
import re
from abc import ABC, abstractmethod # abstract classes

CUTOFF = 20 * 60 * 1000 # only get info for songs that you played for at least CUTOFF milliseconds (getting info takes time, so keep this reasonable, like 20 mins)
TIMOTHY = # SECRET
CLIENT_ID = # SECRET
CLIENT_SECRET = # SECRET

def secs(ms):
    return ms // 1000 % 60

def mins(ms, mod=True):
    ms //= 60000
    if mod:
        ms %= 60
    return ms
    
def hours(ms):
    return ms // 3600000

def hms(ms):
    h = hours(ms)
    if h == 0:
        return f"{mins(ms):>2}:{secs(ms):0>2}"
    return f"{hours(ms):>3}:{mins(ms):0>2}:{secs(ms):0>2}"

def time_to_obj(msg):
    args = []
    for x in re.match(r"(\d+)-(\d+)-(\d+) (\d+):(\d+)", msg).groups():
        x = x.lstrip("0")
        if x == "":
            x = "0"
        args.append(int(x))
    return datetime.datetime(*args)

def obj_to_time(obj):
    return f"{obj.year}-{obj.month:02}-{obj.day:02} {obj.hour:02}:{obj.minute:02}"

def mayterminate():
    if input("Type `yes` to terminate program, type anything else to continue: ").lower() == "yes":
        print("Terminating...")
        exit()

# get playeddict so we know which songs to care about
print("Reading streaming histories...")
playeddict = {}
historydict = {}
FIRST_TIME = None
LAST_TIME = None
k = 0
while True:
    try:
        with open(f"StreamingHistory{k}.json", encoding="utf-8") as file:
            tracks = json.loads(file.read())
            for track in tracks:
                artist = track['artistName']
                name = track['trackName']
                if artist == "Unknown Artist" and name == "Unknown Track":
                    continue
                if (artist, name) not in playeddict:
                    playeddict[(artist, name)] = 0
                    historydict[(artist, name)] = []
                playeddict[(artist, name)] += track['msPlayed']
                endtime = time_to_obj(track['endTime']) + datetime.timedelta(hours=10) # AEST is +10 from UST
                historydict[(artist, name)].append((endtime, track['msPlayed']))
                if len(historydict[(artist, name)]) >= 2:
                    historydict[(artist, name)][-1] = (historydict[(artist, name)][-1][0], historydict[(artist, name)][-1][1] + historydict[(artist, name)][-2][1])
                if FIRST_TIME is None:
                    FIRST_TIME = endtime
                LAST_TIME = endtime
    except FileNotFoundError:
        break
    k += 1

for key in dict(playeddict):
    if playeddict[key] < CUTOFF:
        del playeddict[key], historydict[key]

print(len(playeddict), "songs found. Top 5 are:", ", ".join(key[1] for key in sorted(playeddict, key=lambda x:playeddict[x], reverse=True)[:5]))

# get existing information about these songs
songdata = {}
try:
    with open("songdata.txt", encoding="utf-8") as datafile:
        for line in datafile:
            line = line.strip()
            if line:
                leadartist, trackname, track = line.split(" ||| ")
                track = eval(track) # takes string of dict and replaces it with dict
                songdata[(leadartist, trackname)] = track
except FileNotFoundError:
    print("Failed to read songdata.txt")

albumsongdata = {}
try:
    with open("albumsongdata.txt", encoding="utf-8") as datafile:
        for line in datafile:
            line = line.strip()
            if line:
                leadartist, albumname, tracks = line.split(" ||| ")
                tracks = eval(tracks) # takes string of list of dicts and replaces it with list of dicts
                albumsongdata[(leadartist, albumname)] = tracks
except FileNotFoundError:
    print("Failed to read albumsongdata.txt")

albumcoverdata = {}
try:
    with open("albumcoverdata.txt", encoding="utf-8") as datafile:
        for line in datafile:
            line = line.strip()
            if line:
                leadartist, albumname, image = line.split(" ||| ")
                image = eval(image) # takes string of b'TEXT' and replaces it with bytes object
                albumcoverdata[(leadartist, albumname)] = image
except FileNotFoundError:
    print("Failed to read albumcoverdata.txt")

songdata0 = dict(songdata)
albumsongdata0 = dict(albumsongdata)
albumcoverdata0 = dict(albumcoverdata)

# setup spotify object
SCOPE = "user-library-modify playlist-modify-public"
sp = spotipy.Spotify(auth_manager=spotipy.oauth2.SpotifyOAuth(client_id=CLIENT_ID, client_secret=CLIENT_SECRET, redirect_uri="http://localhost", scope=SCOPE))

# layout constants
DISPLAY_WIDTH = 1472
DISPLAY_HEIGHT = 768
PADDING = 8
CHART_HEIGHT = 704

# create objects
class ChartItem(ABC):
    @abstractmethod
    def name(self):
        pass

    @abstractmethod
    def length(self):
        pass

    @abstractmethod
    def msplayed(self):
        pass

    @abstractmethod
    def get_artists(self):
        pass

    @abstractmethod
    def render(self, rank):
        pass

trackdict = {}
albumdict = {}
artistdict = {}
class Track(ChartItem):
    def __init__(self, obj, leadartist, album=None):
        self.obj = obj
        self.leadartist = leadartist
        self.msplayed_var = 0
        self.history = []

        trackdict[(leadartist, obj['name'])] = self
        
        self.albums = []
        if album is not None:
            self.albums.append(album)
        if "album" in obj:
            album = obj['album']
            if (leadartist, album['name']) not in albumdict:
                Album(album, leadartist)
            temp = albumdict[(leadartist, album['name'])]
            if temp not in self.albums:
                self.albums.append(temp)

        self.artists = []
        for artist in obj['artists']:
            if artist['name'] not in artistdict:
                Artist(artist)
            self.artists.append(artistdict[artist['name']])
            artistdict[artist['name']].tracks.append(self)

    def name(self):
        return self.obj['name']

    def length(self):
        return self.obj['duration_ms']

    def msplayed(self):
        return self.msplayed_var

    def msplayed_interval(self, left, right):
        i = b = len(self.history)
        while b >= 1:
            while i-b >= 0 and self.history[i-b][0] >= left:
                i -= b
            b //= 2

        j = -1
        b = len(self.history)
        while b >= 1:
            while j+b < len(self.history) and self.history[j+b][0] <= right:
                j += b
            b //= 2

        if j == -1 or i == len(self.history):
            return 0
        if i == 0:
            return self.history[j][1]
        return self.history[j][1] - self.history[i-1][1]

    def get_artists(self):
        return ", ".join(artist.name() for artist in self.artists)

    def get_year(self):
        return min(map(lambda album: int(album.obj['release_date'][:4]), self.albums))

    def render(self, rank):
        surf = pygame.Surface()
        if self.mouse_y >= y and self.mouse_y < y + 3*Chart.PADDING + TEXT_HEIGHT:
            if self.clicked:
                if i in self.expanded:
                    self.expanded.remove(i)
                else:
                    self.expanded.add(i)
                    self.albums[i].tracks.sort(key=Track.msplayed, reverse=True)
            if i not in self.expanded:
                pygame.draw.rect(screen, HOVERCOL, (0, y, DISPLAY_WIDTH, TEXT_HEIGHT + 3*Chart.PADDING))
        if i in self.expanded:
            pygame.draw.rect(screen, SELECTCOL, (0, y, DISPLAY_WIDTH, TEXT_HEIGHT + 3*Chart.PADDING))
        bar_length = self.bar_length(self.albums[i], self.albums[0])
        pygame.draw.rect(screen, SPOTIGREEN_DARK, (Chart.PADDING, y, bar_length, TEXT_HEIGHT+2*Chart.PADDING))
        time_text, time_rect = mainfont.render(hms(self.albums[i].msplayed()), (255, 255, 255))
        screen.blit(time_text, (bar_length - time_rect.width, y+Chart.PADDING+(TEXT_HEIGHT-time_rect.height)/2))
        albumcover = pygame.transform.smoothscale(pygame.image.load(io.BytesIO(self.albums[i].cover)), (TEXT_HEIGHT+2*Chart.PADDING, TEXT_HEIGHT+2*Chart.PADDING)).convert()
        screen.blit(albumcover, (bar_length + 2*Chart.PADDING, y))
        mainfontbold.render_to(screen, (5*Chart.PADDING + bar_length + TEXT_HEIGHT, y), self.albums[i].name(), (255, 255, 255))
        mainfontmini.render_to(screen, (5*Chart.PADDING + bar_length + TEXT_HEIGHT, y+TEXT_HEIGHT), f"(#{i+1}) " + self.albums[i].get_artists(), (192, 192, 192))
        if i in self.expanded:
            for j, track in enumerate(self.albums[i].tracks, 1):
                if j > Chart.SUB_TO_SHOW:
                    break
                y += 3*Chart.PADDING + TEXT_HEIGHT
                bar_length = self.bar_length(track, self.albums[0])
                pygame.draw.rect(screen, SPOTIGREEN, (Chart.PADDING, y, bar_length, TEXT_HEIGHT+2*Chart.PADDING))
                time_text, time_rect = mainfont.render(hms(track.msplayed()), (255, 255, 255))
                screen.blit(time_text, (bar_length - time_rect.width, y+Chart.PADDING+(TEXT_HEIGHT-time_rect.height)/2))
                mainfontbold.render_to(screen, (bar_length + 2*Chart.PADDING, y + Chart.PADDING), track.name(), (255, 255, 255))
        y += 3*Chart.PADDING + TEXT_HEIGHT

class Album:
    def __init__(self, obj, leadartist):
        self.obj = obj
        self.leadartist = leadartist

        albumdict[(leadartist, obj['name'])] = self

        if (leadartist, obj['name']) not in albumsongdata:
            print("    ALBUM:", obj['name'])
            albumsongdata[(leadartist, obj['name'])] = sp.album_tracks(self.obj['id'])['items']
                
        self.tracks = []
        for track in albumsongdata[(leadartist, obj['name'])]:
            if (leadartist, track['name']) not in trackdict:
                Track(track, leadartist, album=self)
            self.tracks.append(trackdict[(leadartist, track['name'])])

        self.artists = []
        for artist in obj['artists']:
            if artist['name'] not in artistdict:
                Artist(artist)
            self.artists.append(artistdict[artist['name']])
            artistdict[artist['name']].albums.append(self)

        if (leadartist, obj['name']) not in albumcoverdata:
            print("   ALBUMCOVER:", obj['name'])
            albumcoverdata[(leadartist, obj['name'])] = requests.get(min(self.obj['images'], key=lambda x:x['height'])['url']).content
        self.cover = albumcoverdata[(leadartist, obj['name'])]

    def name(self):
        return self.obj['name']

    def length(self):
        return sum(track.length() for track in self.tracks)

    def msplayed(self):
        return sum(track.msplayed() for track in self.tracks)

    def msplayed_interval(self, left, right):
        return sum(track.msplayed_interval(left, right) for track in self.tracks)

    def get_artists(self):
        return ", ".join(artist.name() for artist in self.artists)

    def render(self, rank):
        if self.mouse_y >= y and self.mouse_y < y + 3*Chart.PADDING + TEXT_HEIGHT:
            if self.clicked:
                if i in self.expanded:
                    self.expanded.remove(i)
                else:
                    self.expanded.add(i)
                    self.albums[i].tracks.sort(key=Track.msplayed, reverse=True)
            if i not in self.expanded:
                pygame.draw.rect(screen, HOVERCOL, (0, y, DISPLAY_WIDTH, TEXT_HEIGHT + 3*Chart.PADDING))
        if i in self.expanded:
            pygame.draw.rect(screen, SELECTCOL, (0, y, DISPLAY_WIDTH, TEXT_HEIGHT + 3*Chart.PADDING))
        bar_length = self.bar_length(self.albums[i], self.albums[0])
        pygame.draw.rect(screen, SPOTIGREEN_DARK, (Chart.PADDING, y, bar_length, TEXT_HEIGHT+2*Chart.PADDING))
        time_text, time_rect = mainfont.render(hms(self.albums[i].msplayed()), (255, 255, 255))
        screen.blit(time_text, (bar_length - time_rect.width, y+Chart.PADDING+(TEXT_HEIGHT-time_rect.height)/2))
        albumcover = pygame.transform.smoothscale(pygame.image.load(io.BytesIO(self.albums[i].cover)), (TEXT_HEIGHT+2*Chart.PADDING, TEXT_HEIGHT+2*Chart.PADDING)).convert()
        screen.blit(albumcover, (bar_length + 2*Chart.PADDING, y))
        mainfontbold.render_to(screen, (5*Chart.PADDING + bar_length + TEXT_HEIGHT, y), self.albums[i].name(), (255, 255, 255))
        mainfontmini.render_to(screen, (5*Chart.PADDING + bar_length + TEXT_HEIGHT, y+TEXT_HEIGHT), f"(#{i+1}) " + self.albums[i].get_artists(), (192, 192, 192))
        if i in self.expanded:
            for j, track in enumerate(self.albums[i].tracks, 1):
                if j > Chart.SUB_TO_SHOW:
                    break
                y += 3*Chart.PADDING + TEXT_HEIGHT
                bar_length = self.bar_length(track, self.albums[0])
                pygame.draw.rect(screen, SPOTIGREEN, (Chart.PADDING, y, bar_length, TEXT_HEIGHT+2*Chart.PADDING))
                time_text, time_rect = mainfont.render(hms(track.msplayed()), (255, 255, 255))
                screen.blit(time_text, (bar_length - time_rect.width, y+Chart.PADDING+(TEXT_HEIGHT-time_rect.height)/2))
                mainfontbold.render_to(screen, (bar_length + 2*Chart.PADDING, y + Chart.PADDING), track.name(), (255, 255, 255))
        y += 3*Chart.PADDING + TEXT_HEIGHT

    def get_year(self):
        return self.obj['release_date'][:4]

class Artist:
    def __init__(self, obj):
        self.obj = obj

        artistdict[obj['name']] = self
        
        self.tracks = []
        self.albums = []

    def name(self):
        return self.obj['name']

    def length(self):
        return sum(track.length() for track in self.tracks)

    def msplayed(self):
        return sum(track.msplayed() for track in self.tracks)

    def msplayed_interval(self, left, right):
        return sum(track.msplayed_interval(left, right) for track in self.tracks)

    def get_artists(self):
        return self.name()

print("Manually calculating the following:")
rank = 1
for key in sorted(playeddict, key=lambda x:playeddict[x], reverse=True):
    leadartist, trackname = key
    if (leadartist, trackname) not in trackdict:
        track = None
        if (leadartist, trackname) in songdata:
            track = Track(songdata[(leadartist, trackname)], leadartist)
        else:
            print(f"    {rank:>{len(str(len(playeddict)))}}/{len(playeddict)}: {leadartist} - {trackname}")
            results = sp.search(f"{trackname} {leadartist}")
            for result in results['tracks']['items']:
                if result['name'] != trackname:
                    continue
                track = Track(result, leadartist)
                break
            else:
                print("    Couldn't find", leadartist, "-", trackname, "on Spotify...")
                continue
            songdata[(leadartist, trackname)] = track.obj
    trackdict[(leadartist, trackname)].msplayed_var += playeddict[(leadartist, trackname)]
    trackdict[(leadartist, trackname)].history = historydict[(leadartist, trackname)]
    rank += 1

print("Storing the newly calculated information...")
with open("songdata.txt", "a", encoding="utf-8") as datafile:
    for key in songdata:
        if key not in songdata0:
            leadartist, trackname = key
            print(leadartist, trackname, songdata[(leadartist, trackname)], sep=" ||| ", file=datafile)

with open("albumsongdata.txt", "a", encoding="utf-8") as datafile:
    for key in albumsongdata:
        if key not in albumsongdata0:
            leadartist, albumname = key
            print(leadartist, albumname, albumsongdata[(leadartist, albumname)], sep=" ||| ", file=datafile)

with open("albumcoverdata.txt", "a", encoding="utf-8") as datafile:
    for key in albumcoverdata:
        if key not in albumcoverdata0:
            leadartist, albumname = key
            print(leadartist, albumname, albumcoverdata[(leadartist, albumname)], sep=" ||| ", file=datafile)

print("Finally ready to launch!")
pygame.init()

HOVERCOL = (64, 64, 64)
SELECTCOL = (96, 96, 96)
SPOTIGREEN = (30, 215, 96)
SPOTIGREEN_DARK = (18, 131, 57)

mainfont = pygame.freetype.Font("ChampagneAndLimousines-7KRB.ttf", 40)
mainfontbold = pygame.freetype.Font("ChampagneAndLimousinesBold-myr2.ttf", 40)
mainfontmini = pygame.freetype.Font("ChampagneAndLimousinesBold-myr2.ttf", 25)

class Slider_Endpoint:
    HEIGHT = 64 - 2*PADDING
    WIDTH = 4

    def __init__(self, x, y, top):
        self.x = x
        self.y = y
        self.top = top

    def get_date(self):
        return FIRST_TIME + (LAST_TIME - FIRST_TIME) * (self.x - PADDING) / (DISPLAY_WIDTH - 2*PADDING)

    def render(self):
        if self.top:
            screen.fill((255, 255, 255), rect=(self.x, self.y+Slider_Endpoint.HEIGHT/2, Slider_Endpoint.WIDTH, Slider_Endpoint.HEIGHT/2))
            draw_text(obj_to_time(self.get_date()).split()[0], (self.x + Slider_Endpoint.WIDTH, self.y), (255, 255, 255), halign=2)
        else:
            screen.fill((255, 255, 255), rect=(self.x, self.y, Slider_Endpoint.WIDTH, Slider_Endpoint.HEIGHT/2))
            draw_text(obj_to_time(self.get_date()).split()[0], (self.x, self.y+Slider_Endpoint.HEIGHT), (255, 255, 255), valign=2)

left_endpoint = Slider_Endpoint(PADDING, CHART_HEIGHT + PADDING, False)
right_endpoint = Slider_Endpoint(DISPLAY_WIDTH - PADDING, CHART_HEIGHT + PADDING, True)

screen = pygame.display.set_mode((DISPLAY_WIDTH, DISPLAY_HEIGHT))
def draw_text(text, pos, colour, font=mainfontmini, halign=0, valign=0):
    x, y = pos
    surf, rect = font.render(text, colour)
    if halign == 2:
        x -= rect.width
    elif halign == 1:
        x -= rect.width / 2
    if valign == 2:
        y -= rect.height
    elif valign == 1:
        y -= rect.height / 2
    screen.blit(surf, (x, y))

class Chart:
    PADDING = PADDING
    BESTBAR_RATIO = 0.5
    SUB_TO_SHOW = 5
    INDENT_WIDTH = 100
    
    def __init__(self):
        self.mode = 0 # 0 track, 1 album, 2 artist
        self.tracks = []
        self.albums = []
        self.artists = []
        self.mouse_x = 0
        self.mouse_y = 0
        self.clicked = False

        self.expanded = set()

        self.screenpos = 0

        self.get_track_order()

    def get_endpoint_dates(self):
        return (left_endpoint.get_date(), right_endpoint.get_date())

    def get_order(self):
        if self.mode == 0:
            self.get_track_order()
        elif self.mode == 1:
            self.get_album_order()
        else:
            self.get_artist_order()

    def get_track_order(self):
        self.tracks = sorted(trackdict.values(), key=lambda track:track.msplayed_interval(*self.get_endpoint_dates()), reverse=True)
        
    def get_album_order(self):
        self.albums = sorted(albumdict.values(), key=lambda album:album.msplayed_interval(*self.get_endpoint_dates()), reverse=True)

    def get_artist_order(self):
        self.artists = sorted(artistdict.values(), key=lambda artist:artist.msplayed_interval(*self.get_endpoint_dates()), reverse=True)

    def incmode(self):
        self.mode = (self.mode + 1) % 3
        if self.mode == 0:
            self.get_track_order()
        elif self.mode == 1:
            self.get_album_order()
        else:
            self.get_artist_order()
        self.scroll(0) # if 3000 tracks and 10 artists and screenpos = 2000, set it to 9
        self.expanded = set()

    def bar_length(self, this, ref):
        return this.msplayed_interval(*self.get_endpoint_dates()) / max(1, ref.msplayed_interval(*self.get_endpoint_dates())) * (DISPLAY_WIDTH-2*Chart.PADDING) * Chart.BESTBAR_RATIO

    def scroll(self, y):
        self.screenpos = max(self.screenpos + y, 0)
        if self.mode == 0:
            self.screenpos = min(self.screenpos, len(self.tracks) - 1)
        elif self.mode == 1:
            self.screenpos = min(self.screenpos, len(self.albums) - 1)
        else:
            self.screenpos = min(self.screenpos, len(self.artists) - 1)

    def render(self):
        TEXT_HEIGHT = mainfontbold.render("dp", (0, 0, 0))[1].height
        y = Chart.PADDING
        if self.mode == 0:
            for i in range(self.screenpos, len(self.tracks)):
                if y >= CHART_HEIGHT:
                    break
                bar_length = self.bar_length(self.tracks[i], self.tracks[0])
                pygame.draw.rect(screen, SPOTIGREEN_DARK, (Chart.PADDING, y, bar_length, TEXT_HEIGHT+2*Chart.PADDING))
                time_text, time_rect = mainfont.render(hms(self.tracks[i].msplayed_interval(*self.get_endpoint_dates())), (255, 255, 255))
                screen.blit(time_text, (bar_length - time_rect.width, y+Chart.PADDING+(TEXT_HEIGHT-time_rect.height)/2))
                if self.tracks[i].albums:
                    albumcover = pygame.transform.smoothscale(pygame.image.load(io.BytesIO(self.tracks[i].albums[0].cover)), (TEXT_HEIGHT+2*Chart.PADDING, TEXT_HEIGHT+2*Chart.PADDING)).convert()
                    screen.blit(albumcover, (bar_length + 2*Chart.PADDING, y))
                mainfontbold.render_to(screen, (5*Chart.PADDING + bar_length + TEXT_HEIGHT, y), self.tracks[i].name(), (255, 255, 255))
                mainfontmini.render_to(screen, (5*Chart.PADDING + bar_length + TEXT_HEIGHT, y+TEXT_HEIGHT), f"(#{i+1}) " + self.tracks[i].get_artists(), (192, 192, 192))
                y += 3*Chart.PADDING + TEXT_HEIGHT
        elif self.mode == 1:
            for i in range(self.screenpos, len(self.albums)):
                if y >= CHART_HEIGHT:
                    break
                if self.mouse_y >= y and self.mouse_y < y + 3*Chart.PADDING + TEXT_HEIGHT:
                    if self.clicked:
                        if i in self.expanded:
                            self.expanded.remove(i)
                        else:
                            self.expanded.add(i)
                            self.albums[i].tracks.sort(key=Track.msplayed, reverse=True)
                    if i not in self.expanded:
                        pygame.draw.rect(screen, HOVERCOL, (0, y, DISPLAY_WIDTH, TEXT_HEIGHT + 3*Chart.PADDING))
                if i in self.expanded:
                    pygame.draw.rect(screen, SELECTCOL, (0, y, DISPLAY_WIDTH, TEXT_HEIGHT + 3*Chart.PADDING))
                bar_length = self.bar_length(self.albums[i], self.albums[0])
                pygame.draw.rect(screen, SPOTIGREEN_DARK, (Chart.PADDING, y, bar_length, TEXT_HEIGHT+2*Chart.PADDING))
                time_text, time_rect = mainfont.render(hms(self.albums[i].msplayed_interval(*self.get_endpoint_dates())), (255, 255, 255))
                screen.blit(time_text, (bar_length - time_rect.width, y+Chart.PADDING+(TEXT_HEIGHT-time_rect.height)/2))
                albumcover = pygame.transform.smoothscale(pygame.image.load(io.BytesIO(self.albums[i].cover)), (TEXT_HEIGHT+2*Chart.PADDING, TEXT_HEIGHT+2*Chart.PADDING)).convert()
                screen.blit(albumcover, (bar_length + 2*Chart.PADDING, y))
                mainfontbold.render_to(screen, (5*Chart.PADDING + bar_length + TEXT_HEIGHT, y), self.albums[i].name(), (255, 255, 255))
                mainfontmini.render_to(screen, (5*Chart.PADDING + bar_length + TEXT_HEIGHT, y+TEXT_HEIGHT), f"(#{i+1}) " + self.albums[i].get_artists(), (192, 192, 192))
                if i in self.expanded:
                    for j, track in enumerate(self.albums[i].tracks, 1):
                        if j > Chart.SUB_TO_SHOW:
                            break
                        y += 3*Chart.PADDING + TEXT_HEIGHT
                        bar_length = self.bar_length(track, self.albums[0])
                        pygame.draw.rect(screen, SPOTIGREEN, (Chart.PADDING, y, bar_length, TEXT_HEIGHT+2*Chart.PADDING))
                        time_text, time_rect = mainfont.render(hms(track.msplayed()), (255, 255, 255))
                        screen.blit(time_text, (bar_length - time_rect.width, y+Chart.PADDING+(TEXT_HEIGHT-time_rect.height)/2))
                        mainfontbold.render_to(screen, (bar_length + 2*Chart.PADDING, y + Chart.PADDING), track.name(), (255, 255, 255))
                y += 3*Chart.PADDING + TEXT_HEIGHT
        elif self.mode == 2:
            for i in range(self.screenpos, len(self.artists)):
                if y >= CHART_HEIGHT:
                    break
                bar_length = self.bar_length(self.artists[i], self.artists[0])
                pygame.draw.rect(screen, SPOTIGREEN_DARK, (Chart.PADDING, y, bar_length, TEXT_HEIGHT+2*Chart.PADDING))
                time_text, time_rect = mainfont.render(hms(self.artists[i].msplayed_interval(*self.get_endpoint_dates())), (255, 255, 255))
                screen.blit(time_text, (bar_length - time_rect.width, y+Chart.PADDING+(TEXT_HEIGHT-time_rect.height)/2))
                if self.artists[i].albums:
                    albumcover = pygame.transform.smoothscale(pygame.image.load(io.BytesIO(self.artists[i].albums[0].cover)), (TEXT_HEIGHT+2*Chart.PADDING, TEXT_HEIGHT+2*Chart.PADDING)).convert()
                elif self.artists[i].tracks:
                    if self.artists[i].tracks[0].albums:
                        albumcover = pygame.transform.smoothscale(pygame.image.load(io.BytesIO(self.artists[i].tracks[0].albums[0].cover)), (TEXT_HEIGHT+2*Chart.PADDING, TEXT_HEIGHT+2*Chart.PADDING)).convert()
                        screen.blit(albumcover, (bar_length + 2*Chart.PADDING, y))
                screen.blit(albumcover, (bar_length + 2*Chart.PADDING, y))
                mainfontbold.render_to(screen, (5*Chart.PADDING + bar_length + TEXT_HEIGHT, y), self.artists[i].name(), (255, 255, 255))
                mainfontmini.render_to(screen, (5*Chart.PADDING + bar_length + TEXT_HEIGHT, y+TEXT_HEIGHT), f"(#{i+1})", (192, 192, 192))
                y += 3*Chart.PADDING + TEXT_HEIGHT

chart = Chart()
print("Launching application...")

def render():
    screen.fill((0, 0, 0))
    
    chart.render()

    screen.fill((0, 0, 0), rect=(0, CHART_HEIGHT, DISPLAY_WIDTH, DISPLAY_HEIGHT-CHART_HEIGHT))

    left_endpoint.render()
    right_endpoint.render()

    pygame.display.update()

##spikedict = {}
##for track in trackdict.values():
##    if not track.history:
##        continue
##    j = 0
##    b = len(track.history)
##    while b >= 1:
##        while j+b < len(track.history) and track.history[j+b][0] - track.history[0][0] < datetime.timedelta(days=1):
##            j += b
##        b //= 2
##    spikedict[track] = track.history[j][1]
##
##for i, track in enumerate(sorted(spikedict, key=lambda x:spikedict[x], reverse=True), 1):
##    print(f"#{i:>{len(str(len(spikedict)))}} ({hms(spikedict[track])})", track.get_artists(), "-", track.name(), f"[{obj_to_time(track.history[0][0]).split()[0]}]")

##playlist = sp.user_playlist_create(TIMOTHY, "top 200 by listening time", description="i have too much free time")
##sp.user_playlist_add_tracks(TIMOTHY, playlist['id'], [track.obj['id'] for track in chart.tracks[:100]])
##sp.user_playlist_add_tracks(TIMOTHY, playlist['id'], [track.obj['id'] for track in chart.tracks[100:200]])

def f(x):
    thing = None
    for artist in artistdict:
        if x in artist:
            thing = artistdict[artist]
            break
    if thing is None:
        for album in albumdict:
            if x in album[1]:
                thing = albumdict[album]
                break
    if thing is None:
        print("Couldn't find", x)
        return

    mn = None
    for track in thing.tracks:
        if track.history:
            if mn is None or track.history[0][0] < mn[0]:
                mn = (track.history[0][0], track.name())
    if mn is None:
        print(thing.name(), "has no listens")
        return
    print(thing.name(), "first listen:", obj_to_time(mn[0]), mn[1])

toquit = False
key_left = False
key_right = False
while True:
    for event in pygame.event.get():
        mouse_x, mouse_y = pygame.mouse.get_pos()
        if event.type == pygame.QUIT:
            toquit = True
            break
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_TAB:
                chart.incmode()
            if event.key == pygame.K_LEFT:
                key_left = True
            if event.key == pygame.K_RIGHT:
                key_right = True
        if event.type == pygame.KEYUP:
            if event.key == pygame.K_LEFT:
                key_left = False
            if event.key == pygame.K_RIGHT:
                key_right = False
        elif event.type == pygame.MOUSEBUTTONDOWN:
            if event.button == 1: # left 1 right 3
                if mouse_y < CHART_HEIGHT:
                    chart.clicked = True
                    chart.mouse_x = mouse_x
                    chart.mouse_y = mouse_y
                else:
                    left_endpoint.x = max(PADDING, min(right_endpoint.x-1, mouse_x))
                    chart.get_order()
            if event.button == 3:
                if mouse_y >= CHART_HEIGHT:
                    right_endpoint.x = max(left_endpoint.x+1, min(DISPLAY_WIDTH-PADDING, mouse_x))
                    chart.get_order()
        elif event.type == pygame.MOUSEWHEEL:
            chart.scroll(-event.y)
    if toquit:
        break

    dx = (key_right - key_left)
    left_endpoint.x = max(PADDING, min(right_endpoint.x-1, left_endpoint.x + dx))
    right_endpoint.x = max(left_endpoint.x+1, min(DISPLAY_WIDTH-PADDING, right_endpoint.x + dx))
    if dx:
        chart.get_order()

    render()

    chart.clicked = False

pygame.quit()
