#!/usr/bin/env python3
"""NORA Cinematic Showcase. Deterministic offline renderer, no production connections.

Source: fedorabakumets/nore-community-bot @ cursor/nora-2-update-d133
Exact vector face of NoraLogo from community_bot/web/intro.js.
UI recreation uses verified labels, class families, and palette from
community_bot/web/{app,home,cabinet,community,shop,interactive,nora-game}.js
and style.css. Demo values are fictional, not production captures.
"""
from __future__ import annotations
import argparse, math, os, subprocess, wave
from pathlib import Path
import numpy as np
import cv2
from PIL import Image,ImageDraw,ImageFont,ImageFilter

HERE=Path(__file__).resolve().parent
OUT=HERE.parent.parent.parent if HERE.parent.name == 'tools' else HERE.parent
W0,H0=(1280,720)
BG='#101011'; PANEL='#1b1b1e'; LINE='#303034'; MUTED='#a1a1aa'; RED='#f32843'; WHITE='#f7f5f1'
def find_font(candidates):
    for f in candidates:
        if f and Path(f).exists():return str(f)
    raise FileNotFoundError('Font unavailable. Set NORA_FONT to an existing TTF/OTF font.')

FONT=find_font([os.getenv('NORA_FONT'),HERE/'fonts'/'Monocraft.ttf',
    '/usr/share/fonts/opentype/inter/Inter-Regular.otf',
    'C:/Windows/Fonts/arial.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'])
BOLD=find_font([os.getenv('NORA_FONT_BOLD'),HERE/'fonts'/'Monocraft.ttf',
    '/usr/share/fonts/opentype/inter/Inter-Bold.otf',
    'C:/Windows/Fonts/arialbd.ttf','/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'])
MONO=find_font([os.getenv('NORA_FONT_MONO'),HERE/'fonts'/'Monocraft.ttf',
    '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf',
    'C:/Windows/Fonts/consola.ttf','C:/Windows/Fonts/cour.ttf'])
FPS=60; SECONDS=22.5

def font(size,bold=False,mono=False):
    return ImageFont.truetype(MONO if mono else BOLD if bold else FONT,int(size))

def rgba(h,a=255):
    if isinstance(h,tuple):return (*h[:3],a)
    h=h.lstrip('#');return tuple(int(h[i:i+2],16) for i in (0,2,4))+(a,)

def text(d,xy,s,size,color=WHITE,bold=False,mono=False,anchor=None):
    s=str(s);xy=tuple(map(int,xy));f=font(size,bold,mono)
    if '🍪' in s and anchor is None:
        before,after=s.split('🍪',1)
        d.text(xy,before,font=f,fill=color,stroke_width=0)
        width=d.textbbox((0,0),before,font=f)[2]
        cx=int(xy[0]+width+max(5,size*.18));cy=int(xy[1]+size*.52);r=max(5,int(size*.32))
        d.ellipse((cx-r,cy-r,cx+r,cy+r),fill='#d69a60',outline='#f8cd8b',width=2)
        for dx,dy in [(-.4,-.2),(.3,-.3),(.1,.42)]:
            rr1=max(2,int(r*.19));xx=cx+int(r*dx);yy=cy+int(r*dy)
            d.ellipse((xx-rr1,yy-rr1,xx+rr1,yy+rr1),fill='#5f3b28')
        if after:d.text((cx+r+4,xy[1]),after,font=f,fill=color)
        return
    d.text(xy,s,font=f,fill=color,anchor=anchor,stroke_width=0)

def rr(d,box,r=14,fill=PANEL,outline=LINE,width=1):
    d.rounded_rectangle(tuple(map(int,box)),int(r),fill=fill,outline=outline,width=width)

def line(d,p,q,color=LINE,width=2): d.line([p,q],fill=color,width=width)

def centered(d,xy,s,size,color=WHITE,bold=False):text(d,xy,s,size,color,bold,anchor='mm')

def make_logo_svg():
    # The exact SVG geometry and fills from production's NoraLogo.markup() in intro.js.
    outline='M123 512 L166 355 Q177 311 217 311 L233 311 L364 311 L376 311 Q417 314 407 355 L398 384 C425 331 478 301 542 301 C608 301 653 340 675 399 L688 351 Q700 312 737 312 L822 312 Q883 312 891 366 Q894 392 882 423 L947 348 Q970 311 1004 311 L1038 311 Q1072 311 1075 351 L1088 516 Q1095 570 1045 570 L1030 570 Q991 570 977 546 Q961 570 926 570 L873 570 Q826 570 815 540 Q803 570 765 570 L701 570 Q662 570 646 546 Q626 570 585 570 L473 570 Q421 570 399 538 Q387 570 347 570 L310 570 Q275 570 266 546 Q252 570 214 570 L164 570 Q115 570 123 512 Z'
    face=[
      ('#fff3e2','M123 512 L166 355 Q177 311 217 311 L233 311 Q274 313 264 355 L256 385 Q254 391 261 391 L298 391 Q304 391 306 384 L315 351 Q325 311 364 311 L376 311 Q417 314 407 355 L379 511 Q372 559 335 559 L310 559 Q270 559 279 519 L287 478 Q289 468 279 468 L247 468 Q239 468 237 477 L227 518 Q217 559 180 559 L160 559 Q115 559 123 512 Z'),
      ('#ff0750','M456 559 C411 539 385 502 388 451 C392 370 455 301 542 301 C621 301 679 364 678 438 C678 491 647 536 592 559 C613 530 616 492 607 463 C598 429 574 407 545 406 C513 404 482 423 462 452 C439 485 441 524 456 559 Z'),
      ('#fff3e2','M658 529 L688 351 Q700 312 737 312 L822 312 Q883 312 891 366 C898 433 860 486 796 486 L770 486 Q763 486 762 492 L754 533 Q746 559 718 559 L694 559 Q664 559 658 529 Z M779 379 Q772 379 770 387 L765 410 Q762 419 770 419 L786 419 Q808 419 810 395 Q812 379 796 379 Z'),
      ('#fff3e2','M839 524 L947 348 Q970 311 1004 311 L1038 311 Q1072 311 1075 351 L1088 516 Q1091 557 1055 559 L1030 559 Q1001 559 1000 521 Q1000 516 995 516 L944 516 Q939 516 937 521 L925 544 Q916 559 896 559 L871 559 Q830 559 839 524 Z M966 440 Q962 450 973 450 L998 450 Q1005 450 1004 442 L1001 400 Q1001 393 996 393 Q990 393 987 399 Z')]
    st=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="100 280 1100 450">', '<g stroke="#050407" stroke-width="12" stroke-linejoin="round">']
    for dx,dy,c in [(44,65,'#00c8ed'),(30,43,'#ff09ae'),(16,22,'#ffd500'),(0,0,'#050407')]:st.append(f'<path d="{outline}" fill="{c}" transform="translate({dx},{dy})"/>')
    st.append('</g><path fill="#050407" d="M820 300 H990 L855 495 H790 Z"/>')
    st.append('<g stroke="#050407" stroke-width="20" stroke-linejoin="round" paint-order="stroke fill">')
    for col,p in face:st.append(f'<path fill="{col}" fill-rule="evenodd" d="{p}"/>')
    st.append('</g></svg>');(HERE/'nora-original.svg').write_text(''.join(st),encoding='utf-8')
    import cairosvg
    cairosvg.svg2png(bytestring=''.join(st).encode(),write_to=str(HERE/'nora-original.png'),output_width=1100,output_height=450)


def draw_navigation(d,active):
    nav=['Главная','Магазин','Коммьюнити','События','Профиль']
    rr(d,(12,972,568,1066),24,'#171719','#343437')
    for i,n in enumerate(nav):
        x=67+i*110
        if n==active:rr(d,(x-48,978,x+48,1059),15,RED,RED)
        col='#120e11' if n==active else MUTED
        # Vector icons avoid missing glyphs on systems lacking symbol fonts.
        iy=999
        if i==0:
            d.polygon([(x-13,iy),(x,iy-13),(x+13,iy),(x+9,iy),(x+9,iy+12),(x-9,iy+12),(x-9,iy)],outline=col)
            d.line((x-13,iy,x,iy-13,x+13,iy),fill=col,width=3)
        elif i==1:
            d.rounded_rectangle((x-11,iy-9,x+11,iy+12),radius=3,outline=col,width=3)
            d.arc((x-7,iy-15,x+7,iy+2),185,355,fill=col,width=3)
        elif i==2:
            d.ellipse((x-11,iy-11,x+3,iy+3),outline=col,width=3)
            d.ellipse((x+0,iy-9,x+12,iy+3),outline=col,width=2)
            d.arc((x-15,iy,x+13,iy+22),180,360,fill=col,width=3)
        elif i==3:
            d.rounded_rectangle((x-12,iy-10,x+12,iy+12),radius=3,outline=col,width=3)
            d.line((x-12,iy-2,x+12,iy-2),fill=col,width=2)
            d.line((x-6,iy-13,x-6,iy-6),fill=col,width=3)
            d.line((x+6,iy-13,x+6,iy-6),fill=col,width=3)
        else:
            d.ellipse((x-7,iy-13,x+7,iy),outline=col,width=3)
            d.arc((x-13,iy-1,x+13,iy+18),180,360,fill=col,width=3)
        centered(d,(x,1035),n,11,col,True)


def draw_header(d,title):
    text(d,(27,29),'N',28,WHITE,True)
    text(d,(49,29),'O',28,RED,True)
    text(d,(73,29),'RA',28,WHITE,True)
    text(d,(29,67),'Санкт-Петербург',13,MUTED)
    rr(d,(474,30,544,72),19,'#242124','#3e3439')
    centered(d,(509,52),'◯',20,RED,True)
    if title:text(d,(28,119),title,36,WHITE,True)


def stat(d,x,y,title,value,sub='',w=248):
    rr(d,(x,y,x+w,y+122),18,PANEL,LINE)
    text(d,(x+17,y+17),title,14,MUTED)
    text(d,(x+17,y+46),value,30,WHITE,True)
    if sub:text(d,(x+17,y+96),sub,12,MUTED)


def screen(view,action=False):
    im=Image.new('RGBA',(580,1080),rgba(BG)); d=ImageDraw.Draw(im)
    # In-app screen layouts approximate actual DOM structure. Text, colors, routes are verified.
    if view=='home':
        draw_header(d,'')
        text(d,(28,139),'Сезон 1 · Bloody Nora',14,RED)
        text(d,(27,177),'Свои',50,WHITE,True);text(d,(158,177),'рядом',50,RED,True)
        text(d,(28,248),'Привет, Участник',18,MUTED)
        rr(d,(24,298,556,610),24,'#201c20','#454248')
        rr(d,(42,315,251,354),17,'#121215','#444249')
        text(d,(56,324),'ВСТРЕЧИ НОРЫ',14,WHITE,True)
        text(d,(43,422),'Скоро встретимся',29,WHITE,True)
        text(d,(45,466),'Новый анонс появится здесь',15,MUTED)
        rr(d,(327,528,538,580),15,RED,RED)
        centered(d,(432,553),'К друзьям ↗',17,'#170d13',True)
        text(d,(28,652),'Вместе или соло',13,MUTED)
        rr(d,(22,682,281,873),22,PANEL,LINE)
        rr(d,(296,682,556,873),22,PANEL,LINE)
        text(d,(42,711),'ИГРЫ',30,WHITE,True)
        text(d,(40,761),'Морской бой',15,MUTED)
        text(d,(40,787),'Мафия · Ракетка',15,MUTED)
        text(d,(315,711),'ПИТОМЕЦ',28,WHITE,True)
        text(d,(316,764),'Твой спутник',15,MUTED)
        text(d,(27,909),'Включайся · Чат сообщества',16,WHITE,True)
    elif view=='community':
        draw_header(d,'Коммьюнити')
        text(d,(28,172),'Свои люди. Одна Нора.',16,MUTED)
        rr(d,(22,222,558,532),20,PANEL,LINE)
        text(d,(39,241),'Топ 5 сегодня',23,WHITE,True)
        line(d,(38,290),(542,290))
        names=['Участник 01','Участник 02','Участник 03','Участник 04']
        for i,n in enumerate(names):
            y=315+i*49
            rr(d,(41,y,74,y+36),17,'#292228','#50404a')
            centered(d,(57,y+18),str(i+1),16,RED,True)
            text(d,(89,y+4),n,16,WHITE,True)
            text(d,(443,y+4),f'{51-i*9}',16,WHITE,True)
        text(d,(39,509),'обновлено только что',12,MUTED)
        rr(d,(22,554,558,646),19,PANEL,LINE)
        text(d,(42,576),'Команда Норы',21,WHITE,True)
        text(d,(42,615),'Участники и модераторы',13,MUTED)
        rr(d,(22,679,558,867),20,PANEL,LINE)
        text(d,(41,700),'Доступные лобби',22,WHITE,True)
        line(d,(40,746),(540,746))
        text(d,(41,771),'Морской бой',21,WHITE,True)
        text(d,(41,807),'Играй вместе с участниками',15,MUTED)
        rr(d,(490,781,538,830),13,RED,RED)
        centered(d,(514,805),'+',29,'#140b0f',True)
    elif view=='profile':
        draw_header(d,'Профиль')
        text(d,(26,176),'Сезон 1 · Bloody Nora',14,RED)
        rr(d,(22,214,558,463),20,PANEL,LINE)
        rr(d,(41,241,183,394),19,'#2d252d','#50424c')
        centered(d,(111,313),'У',72,RED,True)
        text(d,(207,244),'Участник',27,WHITE,True)
        text(d,(207,294),'Участник Норы',16,MUTED)
        text(d,(207,336),'Профиль открыт',14,MUTED)
        text(d,(43,414),'Общайся. Знакомься. Создавай.',15,MUTED)
        stat(d,22,489,'Печеньки','1 280 🍪','Твой баланс',256)
        stat(d,300,489,'Репутация','83 / 100' if action else '82 / 100','Серебро · скидка 5%',258)
        for y,title,sub in [(647,'Кошелёк','Баланс и переводы'),(747,'Питомец','Твой спутник'),(847,'Коммьюнити','Друзья и команда Норы')]:
            rr(d,(22,y,558,y+85),17,PANEL,LINE)
            text(d,(48,y+17),title,21,WHITE,True)
            text(d,(48,y+50),sub,13,MUTED)
            text(d,(511,y+28),'›',29,MUTED)
    elif view=='wallet':
        draw_header(d,'Кошелёк')
        text(d,(26,172),'← Личный кабинет',14,MUTED)
        text(d,(26,237),'Доступно',17,MUTED)
        text(d,(23,281),'1 290 🍪' if action else '1 280 🍪',54,WHITE,True)
        line(d,(25,370),(557,370))
        rr(d,(23,397,282,457),15,RED,RED)
        centered(d,(151,427),'Пополнить',19,'#150b0e',True)
        rr(d,(298,397,554,457),15,'#29292d',LINE)
        centered(d,(426,427),'Перевести ↗',19,WHITE,True)
        text(d,(27,514),'Последние операции',25,WHITE,True)
        for i,(a,b,val) in enumerate([('Награда за активность','Сегодня','+10 🍪'),('Получение печенек','Вчера','+50 🍪'),('Покупка в магазине','Вчера','−35 🍪'),('Подарок','Недавно','+5 🍪')]):
            y=567+i*90
            rr(d,(27,y,83,y+56),16,PANEL,LINE)
            centered(d,(55,y+28),['★','↑','◈','♡'][i],26,RED,True)
            text(d,(102,y+5),a,16,WHITE,True)
            text(d,(103,y+31),b,13,MUTED)
            text(d,(458,y+15),val,16,'#b1e0a6' if val.startswith('+') else WHITE,True)
    elif view=='shop':
        draw_header(d,'Магазин')
        text(d,(28,170),'Твой баланс',15,MUTED)
        text(d,(155,170),'1 290 🍪' if action else '1 280 🍪',18,WHITE,True)
        rr(d,(23,223,557,317),16,PANEL,LINE)
        d.ellipse((40,244,74,278),fill='#bdc3d1',outline='#f2f3f5',width=3)
        text(d,(97,241),'Репутация · 83 / 100' if action else 'Репутация · 82 / 100',14,MUTED)
        text(d,(96,269),'Серебро · скидка 5%',19,WHITE,True)
        rr(d,(23,341,558,549),22,'#261c24','#633642')
        text(d,(44,359),'СЕЗОН 1 · BLOODY NORA',15,RED,True)
        text(d,(43,402),'Магазин Норы',29,WHITE,True)
        text(d,(43,450),'Предметы, подарки и',17,MUTED)
        text(d,(43,474),'возможности сообщества',17,MUTED)
        rr(d,(378,468,535,524),13,RED,RED)
        centered(d,(455,496),'Смотреть ↗',15,'#160b0f',True)
        text(d,(27,595),'Категории',24,WHITE,True)
        for i,(title,description) in enumerate([('Питомцы','Твой спутник'),('Репутация','Защита и уровни'),('Печеньки','Внутренняя валюта')]):
            y=643+i*95
            rr(d,(22,y,557,y+77),17,PANEL,LINE)
            text(d,(44,y+14),title,21,WHITE,True)
            text(d,(44,y+46),description,13,MUTED)
            text(d,(508,y+21),'↗',24,RED,True)
    elif view=='games':
        draw_header(d,'Игры')
        text(d,(26,169),'Вместе или соло',16,MUTED)
        for i,(a,b) in enumerate([('Морской бой','Создать лобби · Играть'),('Мафия','Роли, раунды и голосования'),('Ракетка','Аркадная игра'),('НОРА','Пиксельный 3D-мир')]):
            y=225+i*172
            rr(d,(23,y,557,y+152),21,'#201c22' if i==3 else PANEL,'#633641' if i==3 else LINE)
            rr(d,(45,y+24,139,y+122),19,'#301d26' if i==3 else '#29272e','#4c3b46')
            d.rounded_rectangle((68,y+47,114,y+95),radius=6,outline=RED,width=4); d.line((79,y+71,103,y+71),fill=RED,width=4)
            text(d,(157,y+39),a,26,WHITE,True)
            text(d,(156,y+86),b,15,MUTED)
            text(d,(515,y+68),'›',31,RED)
        text(d,(29,940),'NORA / НОВЫЙ МИР',15,RED,True,mono=True)
    if action and view=='community':
        rr(d,(70,866,509,940),18,'#f7f5f1','#f7f5f1')
        centered(d,(290,902),'Нора · +реп',21,'#101011',True)
    if action and view=='games':
        rr(d,(25,225,555,377),21,'#302027','#f32843',3)
        text(d,(454,330),'Играть ↗',14,RED,True)
    # Replace placeholder Latin header with the real Cyrillic SVG wordmark
    # obtained directly from NoraLogo.markup() in the production UI.
    d.rectangle((18,18,233,108),fill=BG)
    wordmark=Image.open(HERE/'nora-original.png').convert('RGBA')
    wordmark.thumbnail((173,71),Image.Resampling.LANCZOS)
    im.alpha_composite(wordmark,(26,21))
    text(d,(29,87),'Санкт-Петербург',12,MUTED)
    draw_navigation(d,{'home':'Главная','community':'Коммьюнити','profile':'Профиль','wallet':'Профиль','shop':'Магазин','games':'Коммьюнити'}[view])
    return np.array(im)


def floating(kind,action=False):
    im=Image.new('RGBA',(600,230),(0,0,0,0));d=ImageDraw.Draw(im)
    rr(d,(10,10,588,220),27,'#211c21','#524047',2)
    if kind=='meeting':
        text(d,(34,27),'ВСТРЕЧИ НОРЫ',19,RED,True)
        text(d,(33,75),'Скоро встретимся',31,WHITE,True)
        text(d,(34,132),'Встречи, события, общение',19,MUTED)
        rr(d,(411,151,565,199),14,RED,RED)
        centered(d,(488,176),'К друзьям ↗',15,'#190c11',True)
    elif kind=='rep':
        text(d,(33,25),'РЕПУТАЦИЯ',19,RED,True)
        text(d,(35,72),'83 / 100' if action else '82 / 100',42,WHITE,True)
        text(d,(33,141),'Серебро · скидка 5%',20,MUTED,True)
        rr(d,(417,59,565,123),19,'#2f3b32','#57705c')
        centered(d,(491,91),'+реп',24,'#bce8b4',True)
    elif kind=='wallet':
        text(d,(33,27),'КОШЕЛЁК',19,RED,True)
        text(d,(33,71),'1 290 🍪' if action else '1 280 🍪',41,WHITE,True)
        text(d,(33,149),'Последние операции',20,MUTED)
        text(d,(442,153),'+10 🍪',21,'#bce8b4',True)
    elif kind=='shop':
        text(d,(32,25),'МАГАЗИН',18,RED,True)
        text(d,(31,69),'Питомцы · Титулы',26,WHITE,True)
        text(d,(31,112),'Предметы · Подарки',24,WHITE,True)
        text(d,(33,167),'Твоя экономика внутри Норы',16,MUTED)
    elif kind=='battle':
        text(d,(33,26),'ИГРЫ / NORA',19,RED,True,mono=True)
        text(d,(33,78),'Морской бой',31,WHITE,True)
        text(d,(33,137),'Мафия · Ракетка · НОРА',20,MUTED)
    return np.array(im)


def smooth(a,b,x):
    t=np.clip((x-a)/(b-a),0,1);return t*t*(3-2*t)

def opacity_section(t,a,b,fade=.5): return float(smooth(a,a+fade,t)*(1-smooth(b-fade,b,t)))

def base_bg(w,h,seed=0):
    y,x=np.mgrid[0:h,0:w]
    xx=(x-w*.52)/(w*.7);yy=(y-h*.47)/(h*.65)
    glow=np.exp(-(xx*xx*1.9+yy*yy*1.15))
    im=np.zeros((h,w,3),np.uint8)
    im[:]=[11,10,10]
    im[:,:,2]=np.uint8(15+24*glow)
    im[:,:,1]=np.uint8(11+5*glow)
    im[:,:,0]=np.uint8(11+10*glow)
    return im

def alpha_comp(dst,src,x,y,alpha=1.,scale=1.,angle=0,perspective=0):
    if alpha<.006:return
    h,w=src.shape[:2];w2=int(w*scale);h2=int(h*scale)
    if w2<3 or h2<3:return
    if w2>2000 or h2>2000:return
    s=cv2.resize(src,(w2,h2),interpolation=cv2.INTER_AREA if scale<1 else cv2.INTER_LINEAR)
    if angle or perspective:
        # 2.5D camera: affine rotation + vanishing-edge perspective by four corner mapping
        pts=np.float32([[0,0],[w2,0],[w2,h2],[0,h2]])
        a=math.radians(angle);co=math.cos(a);si=math.sin(a)
        cx,cy=w2/2,h2/2
        p=pts-np.float32([[cx,cy]])
        p=np.stack((p[:,0]*co-p[:,1]*si,p[:,0]*si+p[:,1]*co),axis=1)+np.float32([[cx,cy]])
        skew=perspective*w2
        p[0,0]+=skew;p[3,0]+=skew;p[1,0]-=skew;p[2,0]-=skew
        p[0,1]+=abs(perspective)*h2*.25;p[1,1]+=abs(perspective)*h2*.25
        xa,ya=np.min(p,axis=0)-4;xb,yb=np.max(p,axis=0)+4
        ww=max(3,int(xb-xa));hh=max(3,int(yb-ya));p-=np.array([xa,ya],dtype=np.float32)
        mat=cv2.getPerspectiveTransform(pts,p.astype(np.float32))
        s=cv2.warpPerspective(s,mat,(ww,hh),flags=cv2.INTER_LINEAR,borderMode=cv2.BORDER_CONSTANT)
        x+=xa;y+=ya;w2=ww;h2=hh
    x=int(x);y=int(y)
    x1=max(0,x);y1=max(0,y);x2=min(dst.shape[1],x+w2);y2=min(dst.shape[0],y+h2)
    if x1>=x2 or y1>=y2:return
    crop=s[y1-y:y2-y,x1-x:x2-x];a=(crop[:,:,3:4].astype(np.float32)/255.0*alpha)
    base=dst[y1:y2,x1:x2].astype(np.float32)
    dst[y1:y2,x1:x2]=(crop[:,:,:3][:,:,::-1]*a+base*(1-a)).astype(np.uint8)


def make_phone(ui):
    src=Image.fromarray(ui,'RGBA');w,h=src.size
    out=Image.new('RGBA',(w+60,h+64),(0,0,0,0)); d=ImageDraw.Draw(out)
    rr(d,(17,15,w+43,h+46),56,'#050506','#39323a',5)
    rr(d,(28,27,w+32,h+34),44,'#111014','#29272d',2)
    mask=Image.new('L',src.size,0);md=ImageDraw.Draw(mask);md.rounded_rectangle((0,0,w-1,h-1),radius=33,fill=255)
    out.paste(src,(30,31),mask)
    rr(d,(w//2-67,32,w//2+107,72),22,'#08070a','#151219',1)
    rr(d,(w//2+10,36,w//2+20,46),6,'#39252b','#39252b')
    return np.array(out)

def logo_rgba():
    a=Image.open(HERE/'nora-original.png').convert('RGBA')
    box=a.getbbox();a=a.crop(box)
    return np.array(a)

def glow_img(im,w,h,scale=.65):
    rgba1=Image.fromarray(im).convert('RGBA');rgba1=rgba1.resize((int(w*scale),int(h*scale)))
    a=rgba1.getchannel('A').filter(ImageFilter.GaussianBlur(30));gl=Image.new('RGBA',rgba1.size,(230,20,55,0));gl.putalpha(a.point(lambda x:int(x*.42)))
    return np.array(gl)


_title_cache={}
def title_overlay(frame,w,h,title,subtitle,vertical=False,alpha=1):
    if alpha<=.02:return
    key=(w,h,title,subtitle,vertical)
    if key not in _title_cache:
        # Cache tight transparent heading bitmap; do not allocate and blend a
        # full-frame image 60 times every second.
        art=Image.new('RGBA',(min(w,850),255),(0,0,0,0)); d=ImageDraw.Draw(art)
        if vertical:
            x=0;y=0
            if title=='Внутренняя экономика':
                text(d,(x+3,y+3),'Внутренняя',46,WHITE,True)
                text(d,(x+3,y+59),'экономика',46,WHITE,True)
                text(d,(x+3,y+134),subtitle,23,MUTED)
                line(d,(x+3,y+182),(x+123,y+182),RED,5)
            else:
                text(d,(x+3,y+6),title,54 if w>700 else 45,WHITE,True)
                text(d,(x+3,y+81),subtitle,23,MUTED)
                line(d,(x+3,y+129),(x+123,y+129),RED,5)
            origin=(int(w*.08),int(h*.10))
        else:
            x=0;y=0
            if title=='Внутренняя экономика':
                text(d,(x+3,y+6),'Внутренняя',57,WHITE,True)
                text(d,(x+3,y+70),'экономика',57,WHITE,True)
                text(d,(x+3,y+145),subtitle,22,MUTED)
                line(d,(x+3,y+196),(x+163,y+196),RED,5)
            else:
                text(d,(x+3,y+6),title,59,WHITE,True)
                text(d,(x+3,y+95),subtitle,22,MUTED)
                line(d,(x+3,y+153),(x+163,y+153),RED,5)
            origin=(int(w*.08),int(h*.31 if title=='Внутренняя экономика' else h*.37))
        _title_cache[key]=(np.array(art),origin)
    art,origin=_title_cache[key]
    alpha_comp(frame,art,*origin,alpha)

_final_cache={}
def final_tagline(frame,w,h,portrait,alpha):
    if alpha<=.01:return
    key=(w,h,portrait)
    if key not in _final_cache:
        art=Image.new('RGBA',(min(w,950),130),(0,0,0,0));d=ImageDraw.Draw(art)
        centered(d,(art.width//2,65),'Твой мир. Твои правила.',26 if portrait else 29,WHITE)
        _final_cache[key]=np.array(art)
    art=_final_cache[key]
    alpha_comp(frame,art,(w-art.shape[1])//2,int(h*(.61 if portrait else .66))-65,alpha)


def gen_frame(t,portrait=False,assets=None):
    w,h=(720,1280) if portrait else (1280,720)
    bg=assets['bg'].copy()
    # slow drifting red atmosphere, restrained rather than heavy glow
    if t<19:
        cx=int(w*(.61+ .07*math.sin(t*.19)));cy=int(h*(.55+.05*math.cos(t*.13)))
        r=int(min(w,h)*.34)
        if r>0:cv2.circle(bg,(cx,cy),r,(10,12,40),-1,lineType=cv2.LINE_AA) if False else None
    logo=assets['logo']; screens=assets['phones']; cards=assets['cards']
    if t<3.5:
        a=opacity_section(t,0,3.5,.82)
        z=(.40+ .18*smooth(0.2,2.7,t))*(.67 if portrait else 1)
        alpha_comp(bg,logo,w/2-logo.shape[1]*z/2,h*.22-logo.shape[0]*z/2 if portrait else h*.28-logo.shape[0]*z/2,a,z)
    # overlapping content phases, with continuous phone movement and perspective
    windows=[(2.2,6.9,'home','Свои рядом','События · общение · активность'),
             (6.25,10.6,'community','Коммьюнити','Люди. Репутация. Взаимодействия.'),
             (9.95,13.1,'profile','Твой профиль','Репутация и возможности'),
             (12.55,15.8,'shop','Внутренняя экономика','Печеньки · магазин · скидки'),
             (15.1,19.5,'games','Игры НОРЫ','Морской бой · Мафия · Ракетка')]
    for idx,(start,end,key,heading,sub) in enumerate(windows):
        a=opacity_section(t,start,end,.68)
        if a<=.001:continue
        local=(t-start)/(end-start)
        phone=screens[key]
        if (key=='community' and t>=8.1) or (key=='profile' and t>=11.3) or (key=='shop' and t>=14.0) or (key=='games' and t>=17.4):
            phone=assets['phones_action'][key]
        ph,pw=phone.shape[:2]
        if portrait:
            sc=.72 + .03*math.sin(local*math.pi)
            cx=w*.51 + 18*math.sin(local*math.pi*2)
            cy=h*.62 + 30*(local-.5)
            x=cx-pw*sc*.5;y=cy-ph*sc*.50
            title_overlay(bg,w,h,heading,sub,True,a*smooth(start,start+.6,t))
        else:
            sc=.53+.025*math.sin(local*math.pi)
            cx=w*.71+28*math.sin(local*math.pi*1.3)
            cy=h*.53+13*math.cos(local*math.pi)
            x=cx-pw*sc*.5;y=cy-ph*sc*.5
            title_overlay(bg,w,h,heading,sub,False,a*smooth(start,start+.5,t))
        # soft phone shadow
        shadow=assets['shadows'][key]
        alpha_comp(bg,shadow,x-17,y+19,a*.55,sc)
        alpha_comp(bg,phone,x,y,a,sc,angle=(-1.9+3.1*math.sin(local*math.pi)) if not portrait else (-.8+1.4*math.sin(local*math.pi)),perspective=-.04+ .08*local)
        # floating pieces come from known UI groups; depth and slow spring damping
        cardkey={0:'meeting',1:'rep',2:'rep',3:'wallet',4:'battle'}[idx]
        card=cards[cardkey]
        if (cardkey=='rep' and t>=8.1) or (cardkey=='wallet' and t>=14.0):
            card=assets['cards_action'][cardkey]
        ca=a*smooth(start+.6,start+1.3,t)*(1-smooth(end-.65,end,t))
        if ca>.001:
            if portrait:
                cs=.43;x2=w*.51-card.shape[1]*cs*.5+10*math.sin(t*.7);y2=h*.912+10*math.sin(local*math.pi)
            else:
                cs=.66;x2=w*.40-card.shape[1]*cs*.5+30*math.sin(t*.7);y2=h*.76-card.shape[0]*cs*.5+16*math.sin(local*math.pi)
            alpha_comp(bg,card,x2,y2,ca,cs,angle=-2+2*math.sin(t*.5),perspective=.035)
    if t>=18.8:
        a=smooth(18.8,20.1,t)*(1-smooth(21.65,22.5,t))
        # final centered original mark
        scale=(.47 if portrait else .62)*(0.92+.08*smooth(19,20.4,t))
        cx=w*.5;cy=h*(.43 if portrait else .43)
        alpha_comp(bg,assets['logo_glow'],cx-assets['logo_glow'].shape[1]*scale/2,cy-assets['logo_glow'].shape[0]*scale/2,a*.66,scale)
        alpha_comp(bg,logo,cx-logo.shape[1]*scale/2,cy-logo.shape[0]*scale/2,a,scale)
        title_overlay(bg,w,h,'','',portrait,0)
        final_tagline(bg,w,h,portrait,a*smooth(19.7,20.45,t))
    # fade to dark at last second
    if t>21.7:bg=(bg.astype(np.float32)*(1-smooth(21.7,22.5,t))).astype(np.uint8)
    return bg


def audio():
    n=int(FPS*SECONDS*735); sr=44100
    t=np.arange(n)/sr
    s=np.zeros(n,np.float32)
    # original sound design: synthesis only, no sourced/copyrighted audio.
    def whoosh(at,secs=.9,amp=.17):
        a=int(at*sr);m=int(secs*sr);rng=np.random.default_rng(1234+a)
        noise=rng.normal(0,1,m)
        filt=np.convolve(noise,np.ones(13)/13,mode='same')
        env=np.sin(np.linspace(0,math.pi,m))**2
        s[a:a+m] += (filt*env*amp).astype(np.float32)
    def tone(at,freq=92,secs=1.1,amp=.13):
        a=int(at*sr);m=int(secs*sr)
        ts=np.arange(m)/sr; env=np.exp(-ts*4)*np.minimum(1,ts*65)
        s[a:a+m]+=(amp*env*(np.sin(ts*2*math.pi*freq)+.24*np.sin(ts*2*math.pi*freq*1.5))).astype(np.float32)
    for i,at in enumerate([.5,2.7,6.35,10.1,12.7,15.35,19.15]):
        whoosh(at,.8,.12);tone(at+.08,87+i*13,.95,.13)
    # quiet sub-bed, very subtle cinematic pulse
    s+=.011*np.sin(t*2*math.pi*47)*np.sin(t*math.pi/3.2)**4
    s=np.clip(s,-.88,.88)
    dest=HERE/'sound-design.wav'
    with wave.open(str(dest),'wb') as f:
        f.setnchannels(2);f.setsampwidth(2);f.setframerate(sr)
        z=(s*32767).astype('<i2');f.writeframes(np.column_stack([z,z]).ravel().tobytes())
    return dest


def render(portrait=False,preview=None,quick=False):
    make_logo_svg()
    screens={k:make_phone(screen(k)) for k in ('home','community','profile','wallet','shop','games')}
    screens_action={k:make_phone(screen(k,True)) for k in ('community','profile','wallet','shop','games')}
    cards={k:floating(k) for k in ('meeting','rep','wallet','shop','battle')}
    cards_action={k:floating(k,True) for k in ('rep','wallet')}
    logo=logo_rgba()
    # Blur into padded transparent canvas: avoid visible glow rectangle edges.
    pad=180
    padded=Image.new('RGBA',(logo.shape[1]+pad*2,logo.shape[0]+pad*2),(0,0,0,0))
    padded.alpha_composite(Image.fromarray(logo),(pad,pad))
    glow_alpha=padded.getchannel('A').filter(ImageFilter.GaussianBlur(64)).point(lambda v:int(v*.27))
    glow=Image.new('RGBA',padded.size,(230,18,51,0))
    glow.putalpha(glow_alpha)
    gl=np.array(glow)
    shadows={}
    for k,v in screens.items():
        si=Image.fromarray(v)
        shadow=Image.new('RGBA',si.size,(0,0,0,0))
        shadow.putalpha(si.getchannel('A').filter(ImageFilter.GaussianBlur(24)).point(lambda x:int(x*.7)))
        shadows[k]=np.array(shadow)
    w,h=(720,1280) if portrait else (1280,720)
    a={'bg':base_bg(w,h),'logo':logo,'logo_glow':gl,'phones':screens,'phones_action':screens_action,'cards':cards,'cards_action':cards_action,'shadows':shadows}
    if preview is not None:
        frame=gen_frame(float(preview),portrait,a)
        name=f'preview_{"vertical" if portrait else "horizontal"}_{preview}.png'
        cv2.imwrite(str(OUT/'preview'/name),cv2.resize(frame,(w*3//2,h*3//2)))
        print('preview:',name,flush=True);return
    outfile=OUT/('NORA_showcase_vertical_1080x1920.mp4' if portrait else 'NORA_showcase_horizontal_1920x1080.mp4')
    aud=HERE/'sound-design.wav'
    cmd=['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pix_fmt','bgr24','-s',f'{w}x{h}','-r',str(FPS),'-i','pipe:0','-i',str(aud),'-vf',f'scale={w*3//2}:{h*3//2}:flags=bicubic,format=yuv420p','-c:v','libx264','-preset','ultrafast','-crf','20','-profile:v','high','-r',str(FPS),'-c:a','aac','-b:a','160k','-ar','44100','-shortest','-movflags','+faststart',str(outfile)]
    print('render:',outfile,flush=True)
    p=subprocess.Popen(cmd,stdin=subprocess.PIPE)
    frames=int(FPS*SECONDS)
    try:
        for i in range(frames):
            fr=gen_frame(i/FPS,portrait,a)
            p.stdin.write(fr.tobytes())
            if i and i%300==0:print('frame',i,'/',frames,flush=True)
        p.stdin.close();code=p.wait()
        if code:raise RuntimeError(f'FFmpeg exited with code {code}')
    except (BrokenPipeError,KeyboardInterrupt):
        p.stdin.close();p.wait();raise
    print('finished',outfile, outfile.stat().st_size,flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--portrait',action='store_true')
    ap.add_argument('--preview',type=float)
    ap.add_argument('--audio',action='store_true')
    args=ap.parse_args()
    OUT.joinpath('preview').mkdir(parents=True,exist_ok=True)
    if args.audio:audio()
    else:render(args.portrait,args.preview)