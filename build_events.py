#!/usr/bin/env python3
# -*- coding: utf-8 -*-
'''
build_events.py — SunFest «Сила Солнца» event extractor.

Analogous to the WhatsApp extraction step in merhav-bari, but the SOURCE here is
the festival website https://sunfest.co.il (pages: /, /plan.html, /payment.html).
This script transcribes the festival's official schedule + pricing into events.json
following the schema in README.md. Re-run it if the website schedule changes.

    python build_events.py        # writes events.json

Then run:  python pipeline.py
'''
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

BASE          = 'https://sunfest.co.il/'
FESTIVAL_LINK = BASE                 # the festival's own explanation page (home)
FALLBACK_LINK = BASE + 'plan.html'   # used when an event has no dedicated page
SITE       = 'https://sunfest.co.il/'

# Each master-class title → its explanation page on sunfest.co.il
PAGE = {
    'Круг знакомства': 'krug-znakomstv.html',
    'Медитация «Львиное сердце»': 'lions-heart-meditation-lvinoe-serdtse.html',
    'Добаюкивание': 'dobayukivanie.html',
    'Внутренний ребёнок и исцеление детских травм': 'vstrecha-s-vnutrennim-rebenkom.html',
    'Аюрведические секреты красоты: сияние изнутри': 'ayurvedicheskie-sekrety-krasoty.html',
    'Звучать всем телом': 'zvuchat-vsem-telom.html',
    'ГДЕ МОИ ДЕНЬГИ? Ловушка духовности и проработок': 'gde-moi-dengi.html',
    'Исцеляющее касание': 'istselyayuschee-kasanie.html',
    'Официальное открытие фестиваля. Концерт Frisson Trio': 'frisson-trio.html',
    'Хатха-йога': 'hatkha-yoga.html',
    'Дыхание с Источником': 'dihanie-istochnikom.html',
    'Гвоздестояние. Тело помнит всё!': 'gvozdi.html',
    'Смехо-йога': 'smehoyoga.html',
    'Цигун': 'tsigun.html',
    'Психосоматическая реабилитационная кинезиология': 'psihosamoticheskaya-reabilitatsionnaya-kineziologiya.html',
    'Безлимитная мотивация, или Как добиться успеха': 'bezlimitnaya-motivatsiya-ili-kak-dobitsya-uspeha.html',
    'Голос души: навигация по Хьюман Дизайну': 'dizayn-cheloveka.html',
    'Процессуальная работа: услышать и проявить скрытое в себе': 'protsessualnaya-rabota-kak-uslyshat-i-proyavit-skrytoe-v-sebe.html',
    '«Быть в потоке». Нейрографика': 'byt-v-potoke.html',
    'Ментальное здоровье и целостность': 'mentalnoe-zdorove-i-tselostnost.html',
    'Алхимия прикосновения': 'alhimiya-prikosnoveniya.html',
    '4 вида наслаждения': 'naslajdenie.html',
    'Аутентичное движение': 'autentichnoe-dvizhenie.html',
    'AI и человек будущего: как ИИ меняет бизнес и жизнь': 'ai-i-chelovek-buduschego-kak-iskusstvennyy-intellekt-menyaet-biznes-rabotu-i-nashu-zhizn.html',
    'Естественное звучание': 'raskrytie-zvuchaniya.html',
    'Женский круг с нейрографическими практиками «ПЕРЕХОД»': 'zhenskiy-krug-s-neyrograficheskimi-praktikami-perehod.html',
    'Танец отношений': 'tanets-otnosheniy.html',
    'Пробуждение внутреннего целителя': 'celitel.html',
    'Массаж в 10 рук с музыкальным сопровождением': 'v-ritme-serdtsa-massazh-v-10-ruk.html',
    'Нейрографика. Язык Вселенной: линии, меняющие реальность': 'yazyk-vselennoy-linii-kotorye-menyayut-realnost.html',
    'Линия времени': 'liniya-vremeni-i-glubokaya-prorabotka-travm-detstva.html',
    'Искусство быть желанной. Коды женского соблазна (для девушек)': 'iskusstvo-byt-zhelannoy-kody-zhenskogo-soblazna.html',
    'PRO отношения 3.0 (только для мужчин)': 'muzhchina-novogo-vremeni.html',
    'Дао эмоций': 'dao-emotsiy.html',
    'Алхимия дыхания': 'alkhimiya-dyhania.html',
    'Женский сакральный танец': 'zhenskiy-sakralniy-tanec.html',
    'Тайская йога': 'tayskaya-yoga.html',
    'Интуитивный контактный танец': 'intuitivnyy-kontaktnyy-tanets.html',
    'Воплощение мечты — сейчас!': 'voploschenie-mechty-seichas.html',
    'Путь с Отцом': 'put-s-ottsom.html',
    'Бизнес-расстановки: деньги, команда и энергия роста': 'bizness-rasstanovki.html',
    'Голос как энергия': 'golos.html',
    'Отношения: от первой искры до зрелой любви': 'otnosheniya-ot-pervoy-iskry-do-zreloy-lyubvi.html',
    'Тибетские чаши. Звук, который ведёт': 'tibetskie-chashi-zvuk-kotoryy-vedyot.html',
    # No dedicated page (linked to the schedule instead):
    #   'Практики управления энергией' + the late-night ceremonies / closing
}


def event_link(title):
    slug = PAGE.get(title)
    return (BASE + slug) if slug else FALLBACK_LINK


# Master-class category (the filter groups on master-klassy.html), by page slug
CATEGORY = {
    'alkhimiya-dyhania.html': 'breath',
    'alhimiya-prikosnoveniya.html': 'body',
    'ai-i-chelovek-buduschego-kak-iskusstvennyy-intellekt-menyaet-biznes-rabotu-i-nashu-zhizn.html': 'business',
    'autentichnoe-dvizhenie.html': 'contact',
    'ayurvedicheskie-sekrety-krasoty.html': 'body',
    'bezlimitnaya-motivatsiya-ili-kak-dobitsya-uspeha.html': 'business',
    'bizness-rasstanovki.html': 'psychology',
    'byt-v-potoke.html': 'creative',
    'v-ritme-serdtsa-massazh-v-10-ruk.html': 'body',
    'voploschenie-mechty-seichas.html': 'psychology',
    'naslajdenie.html': 'psychology',
    'vstrecha-s-vnutrennim-rebenkom.html': 'psychology',
    'gde-moi-dengi.html': 'psychology',
    'dizayn-cheloveka.html': 'creative',
    'golos.html': 'music',
    'dao-emotsiy.html': 'psychology',
    'dobayukivanie.html': 'body',
    'dihanie-istochnikom.html': 'breath',
    'raskrytie-zvuchaniya.html': 'music',
    'zhenskiy-krug-s-neyrograficheskimi-praktikami-perehod.html': 'creative',
    'zhenskiy-sakralniy-tanec.html': 'body',
    'zvuchat-vsem-telom.html': 'music',
    'istselyayuschee-kasanie.html': 'body',
    'frisson-trio.html': 'music',
    'krug-znakomstv.html': 'love',
    'lions-heart-meditation-lvinoe-serdtse.html': 'body',
    'liniya-vremeni-i-glubokaya-prorabotka-travm-detstva.html': 'psychology',
    'mentalnoe-zdorove-i-tselostnost.html': 'psychology',
    'otnosheniya-ot-pervoy-iskry-do-zreloy-lyubvi.html': 'love',
    'celitel.html': 'body',
    'protsessualnaya-rabota-kak-uslyshat-i-proyavit-skrytoe-v-sebe.html': 'psychology',
    'psihosamoticheskaya-reabilitatsionnaya-kineziologiya.html': 'body',
    'put-s-ottsom.html': 'psychology',
    'smehoyoga.html': 'breath',
    'tanets-otnosheniy.html': 'contact',
    'tayskaya-yoga.html': 'body',
    'tibetskie-chashi-zvuk-kotoryy-vedyot.html': 'music',
    'hatkha-yoga.html': 'body',
    'tsigun.html': 'body',
    'yazyk-vselennoy-linii-kotorye-menyayut-realnost.html': 'creative',
    'muzhchina-novogo-vremeni.html': 'love',
    'intuitivnyy-kontaktnyy-tanets.html': 'contact',
}
CAT_LABEL = {
    'all':          'Все мастер-классы',
    'body':         'Телесные практики и энергия',
    'breath':       'Дыхание и трансформационные практики',
    'creative':     'Творчество и самовыражение',
    'music':        'Музыка, звук, голос и саундхиллинг',
    'business':     'Деньги, реализация и бизнес',
    'psychology':   'Психология и глубинная трансформация',
    'love':         'Отношения и близость',
    'spirituality': 'Духовные и эзотерические практики',
    'contact':      'Движение, танец, контакт',
}
# Events with no dedicated master-class page get a category by hand:
TITLE_CAT_OVERRIDE = {
    'Практики управления энергией': 'body',
}


def category_label(title):
    cat = CATEGORY.get(PAGE.get(title)) or TITLE_CAT_OVERRIDE.get(title, 'all')
    return CAT_LABEL[cat]


# Event figure (og:image) per master-class page slug — shown as the card image
IMAGE = {
    'ai-i-chelovek-buduschego-kak-iskusstvennyy-intellekt-menyaet-biznes-rabotu-i-nashu-zhizn.html': 'https://sunfest.co.il/images/upload-20260209-134632-6989c91889640-og.jpg',
    'alhimiya-prikosnoveniya.html': 'https://sunfest.co.il/images/upload-20260208-023009-6987d91105753-og.jpg',
    'alkhimiya-dyhania.html': 'https://sunfest.co.il/images/upload-20260208-021756-6987d63411c49-og.jpg',
    'autentichnoe-dvizhenie.html': 'https://sunfest.co.il/images/upload-20260203-233152-69826948b767b-og.jpg',
    'ayurvedicheskie-sekrety-krasoty.html': 'https://sunfest.co.il/images/upload-20260205-152500-69849a2ccd3dd-og.jpg',
    'bezlimitnaya-motivatsiya-ili-kak-dobitsya-uspeha.html': 'https://sunfest.co.il/images/upload-20260209-142516-6989d22ccb65e-og.jpg',
    'bizness-rasstanovki.html': 'https://sunfest.co.il/images/upload-20260208-021756-6987d63411c49-og.jpg',
    'celitel.html': 'https://sunfest.co.il/images/upload-20260208-021756-6987d63411c49-og.jpg',
    'dao-emotsiy.html': 'https://sunfest.co.il/images/upload-20260208-012915-6987cacb0f466-og.jpg',
    'dihanie-istochnikom.html': 'https://sunfest.co.il/images/upload-20260208-021623-6987d5d794d0b-og.jpg',
    'dizayn-cheloveka.html': 'https://sunfest.co.il/images/upload-20260205-152500-69849a2ccd3dd-og.jpg',
    'dobayukivanie.html': 'https://sunfest.co.il/images/upload-20260208-021623-6987d5d794d0b-og.jpg',
    'frisson-trio.html': 'https://sunfest.co.il/images/upload-20260531-202908-6a1c9a14663b5.png',
    'gde-moi-dengi.html': 'https://sunfest.co.il/images/upload-20260208-022756-6987d88cc8979-og.jpg',
    'golos.html': 'https://sunfest.co.il/images/upload-20260208-013756-6987ccd49a92f-og.jpg',
    'hatkha-yoga.html': 'https://sunfest.co.il/images/upload-20260208-015916-6987d1d45d4b0-og.jpg',
    'intuitivnyy-kontaktnyy-tanets.html': 'https://sunfest.co.il/images/upload-20260203-233152-69826948b767b-og.jpg',
    'istselyayuschee-kasanie.html': 'https://sunfest.co.il/images/upload-20260208-012915-6987cacb0f466-og.jpg',
    'krug-znakomstv.html': 'https://sunfest.co.il/images/upload-20260605-214237-6a2342cd05036-og.jpg',
    'liniya-vremeni-i-glubokaya-prorabotka-travm-detstva.html': 'https://sunfest.co.il/images/upload-20260205-153132-69849bb49b03b-og.jpg',
    'lions-heart-meditation-lvinoe-serdtse.html': 'https://sunfest.co.il/images/upload-20260208-023009-6987d91105753-og.jpg',
    'mentalnoe-zdorove-i-tselostnost.html': 'https://sunfest.co.il/images/upload-20260208-021623-6987d5d794d0b-og.jpg',
    'naslajdenie.html': 'https://sunfest.co.il/images/upload-20260208-022756-6987d88cc8979-og.jpg',
    'otnosheniya-ot-pervoy-iskry-do-zreloy-lyubvi.html': 'https://sunfest.co.il/images/upload-20260208-023009-6987d91105753-og.jpg',
    'protsessualnaya-rabota-kak-uslyshat-i-proyavit-skrytoe-v-sebe.html': 'https://sunfest.co.il/images/upload-20260208-012915-6987cacb0f466-og.jpg',
    'psihosamoticheskaya-reabilitatsionnaya-kineziologiya.html': 'https://sunfest.co.il/images/upload-20260531-202744-6a1c99c033e26-og.jpg',
    'put-s-ottsom.html': 'https://sunfest.co.il/images/upload-20260208-021623-6987d5d794d0b-og.jpg',
    'raskrytie-zvuchaniya.html': 'https://sunfest.co.il/images/upload-20260205-152932-69849b3c6bb6b-og.jpg',
    'smehoyoga.html': 'https://sunfest.co.il/images/upload-20260205-151012-698496b45d19e-og.jpg',
    'tanets-otnosheniy.html': 'https://sunfest.co.il/images/upload-20260208-013756-6987ccd49a92f-og.jpg',
    'tayskaya-yoga.html': 'https://sunfest.co.il/images/upload-20260605-214144-6a2342985c672-og.jpg',
    'tibetskie-chashi-zvuk-kotoryy-vedyot.html': 'https://sunfest.co.il/images/upload-20260531-202835-6a1c99f341dbe-og.jpg',
    'tsigun.html': 'https://sunfest.co.il/images/upload-20260605-214144-6a2342985c672-og.jpg',
    'v-ritme-serdtsa-massazh-v-10-ruk.html': 'https://sunfest.co.il/images/upload-20260609-225859-6a289ab3a2e8d-og.jpg',
    'voploschenie-mechty-seichas.html': 'https://sunfest.co.il/images/upload-20260208-022847-6987d8bfa45ba-og.jpg',
    'vstrecha-s-vnutrennim-rebenkom.html': 'https://sunfest.co.il/images/upload-20260205-153132-69849bb49b03b-og.jpg',
    'yazyk-vselennoy-linii-kotorye-menyayut-realnost.html': 'https://sunfest.co.il/images/upload-20260208-012645-6987ca35be69b-og.jpg',
    'zhenskiy-krug-s-neyrograficheskimi-praktikami-perehod.html': 'https://sunfest.co.il/images/upload-20260208-015540-6987d0fc4dc94-og.jpg',
    'zhenskiy-sakralniy-tanec.html': 'https://sunfest.co.il/images/upload-20260208-015540-6987d0fc4dc94-og.jpg',
    'zvuchat-vsem-telom.html': 'https://sunfest.co.il/images/upload-20260203-233152-69826948b767b-og.jpg',
}


def event_image(title):
    return IMAGE.get(PAGE.get(title))
POSTER     = 'https://sunfest.co.il/images/page-header-bg.jpg'  # festival hero banner (og:image is 404)
CITY       = None           # location intentionally omitted from cards
POST_DATE  = '2026-06-09'   # date the schedule was published / last seen

CONTACT = {
    'phone': [{'number': '055-661-7297', 'name': 'SunFest'}],
    'telegram': [],
    'instagram': ['sunfest.il'],
    'other': [],
}

# (date, weekday-russian) per festival day
DAYS = {
    18: '2026-06-18',
    19: '2026-06-19',
    20: '2026-06-20',
}

# slots: (day, start, end, master_or_None, title)
SLOTS = [
    # ── Четверг, 18 июня — Открытие ──
    (18, '16:30', '18:00', 'Эрик Розенталь',      'Круг знакомства'),
    (18, '16:30', '18:00', 'Вишвас',              'Медитация «Львиное сердце»'),
    (18, '16:30', '18:00', 'Эзра Щебальский',     'Добаюкивание'),
    (18, '19:00', '20:30', 'Борис Мельцер',       'Внутренний ребёнок и исцеление детских травм'),
    (18, '19:00', '20:30', 'Оксана Керен-Злата',  'Аюрведические секреты красоты: сияние изнутри'),
    (18, '19:00', '20:30', 'Катя Величко',        'Звучать всем телом'),
    (18, '19:00', '20:30', 'Кирилл Саблин',       'ГДЕ МОИ ДЕНЬГИ? Ловушка духовности и проработок'),
    (18, '19:00', '20:30', 'Константин Грингут',  'Исцеляющее касание'),
    (18, '21:00', '22:30', 'Frisson Trio',        'Официальное открытие фестиваля. Концерт Frisson Trio'),
    (18, '22:30', None,    None,                  'Праздник Летнего Солнцестояния: прыжки через костёр, музыкальный джем'),

    # ── Пятница, 19 июня — Погружение ──
    (19, '07:00', '08:30', 'Либи Гордон',         'Хатха-йога'),
    (19, '07:00', '08:30', 'Эзра Щебальский',     'Дыхание с Источником'),
    (19, '07:00', '08:30', 'Александра Тропп',    'Гвоздестояние. Тело помнит всё!'),
    (19, '07:00', '08:30', 'Митя Колтун',         'Смехо-йога'),
    (19, '07:00', '08:30', 'Мария Рабин',         'Цигун'),
    (19, '09:30', '11:00', 'Ян Осадчий',          'Психосоматическая реабилитационная кинезиология'),
    (19, '09:30', '11:00', 'Семён Графман',       'Безлимитная мотивация, или Как добиться успеха'),
    (19, '09:30', '11:00', 'Оксана Керен-Злата',  'Голос души: навигация по Хьюман Дизайну'),
    (19, '09:30', '11:00', 'Константин Грингут',  'Процессуальная работа: услышать и проявить скрытое в себе'),
    (19, '09:30', '11:00', 'Жанна Касплер-Алон',  '«Быть в потоке». Нейрографика'),
    (19, '11:30', '13:00', 'Эзра Щебальский',     'Ментальное здоровье и целостность'),
    (19, '11:30', '13:00', 'Вишвас',              'Алхимия прикосновения'),
    (19, '11:30', '13:00', 'Кирилл Саблин',       '4 вида наслаждения'),
    (19, '14:30', '16:00', 'Катя Величко',        'Аутентичное движение'),
    (19, '14:30', '16:00', 'Алекс Кап',           'AI и человек будущего: как ИИ меняет бизнес и жизнь'),
    (19, '14:30', '16:00', 'Роман Тизенберг',     'Естественное звучание'),
    (19, '14:30', '16:00', 'Ольга Шнайдер (Симери)', 'Женский круг с нейрографическими практиками «ПЕРЕХОД»'),
    (19, '16:30', '18:00', 'Александр Коско',     'Танец отношений'),
    (19, '16:30', '18:00', 'Эзра Щебальский',     'Добаюкивание'),
    (19, '16:30', '18:00', 'Ольга Альвайс',       'Пробуждение внутреннего целителя'),
    (19, '16:30', '18:00', 'Даниэль Деглин и Инна Головичер', 'Массаж в 10 рук с музыкальным сопровождением'),
    (19, '16:30', '18:00', 'Мири Мельничук',      'Нейрографика. Язык Вселенной: линии, меняющие реальность'),
    (19, '19:00', '20:30', 'Борис Мельцер',       'Линия времени'),
    (19, '19:00', '20:30', 'Елена Чудная',        'Искусство быть желанной. Коды женского соблазна (для девушек)'),
    (19, '19:00', '20:30', 'Марк Мальцер',        'PRO отношения 3.0 (только для мужчин)'),
    (19, '19:00', '20:30', 'Михаэль Натанэль',    'Практики управления энергией'),
    (19, '19:00', '20:30', 'Константин Грингут',  'Дао эмоций'),
    (19, '20:45', '22:00', 'Ольга Альвайс',       'Алхимия дыхания'),
    (19, '22:00', None,    None,                  'Экстатик-денс в наушниках (дресс-код белый), джем, посиделки у костра'),

    # ── Суббота, 20 июня — Интеграция ──
    (20, '07:00', '08:30', 'Либи Гордон',         'Хатха-йога'),
    (20, '07:00', '08:30', 'Эзра Щебальский',     'Дыхание с Источником'),
    (20, '07:00', '08:30', 'Митя Колтун',         'Смехо-йога'),
    (20, '07:00', '08:30', 'Ольга Шнайдер (Симери)', 'Женский сакральный танец'),
    (20, '07:00', '08:30', 'Мария Рабин',         'Тайская йога'),
    (20, '07:00', '08:30', 'Александра Тропп',    'Гвоздестояние. Тело помнит всё!'),
    (20, '09:30', '11:00', 'Катя Величко',        'Интуитивный контактный танец'),
    (20, '09:30', '11:00', 'Игорь Юровский',      'Воплощение мечты — сейчас!'),
    (20, '09:30', '11:00', 'Эзра Щебальский',     'Путь с Отцом'),
    (20, '11:15', '12:45', 'Ольга Альвайс',       'Бизнес-расстановки: деньги, команда и энергия роста'),
    (20, '11:15', '12:45', 'Александр Коско',     'Голос как энергия'),
    (20, '11:15', '12:45', 'Вишвас',              'Отношения: от первой искры до зрелой любви'),
    (20, '11:15', '12:45', 'Александра Тропп',    'Тибетские чаши. Звук, который ведёт'),
    (20, '13:10', '14:00', None,                  'Закрытие фестиваля. Саундхиллинг, интеграция'),
]


def classify(title, master):
    t = title.lower()
    if master == 'Frisson Trio' or 'концерт' in t:
        return 'concert'
    if 'йога' in t or 'цигун' in t:
        return 'yoga'
    if 'медитац' in t:
        return 'meditation'
    if 'танец' in t or 'денс' in t or 'движение' in t:
        return 'dance'
    if any(k in t for k in ('костёр', 'солнцестоян', 'закрытие', 'джем', 'праздник')):
        return 'ceremony'
    return 'workshop'


def make_workshop(day, start, end, master, title):
    etype = classify(title, master)
    desc = f'Ведущий: {master}.' if master else 'Общефестивальное событие.'
    raw = f'{day} июня 2026'
    return {
        'title': title,
        'event_type': etype,
        'category': category_label(title),
        'facilitator': master,
        'status': 'scheduled',
        'date_only': DAYS[day],
        'end_date_only': None,
        'start_time_only': start,
        'end_time_only': end,
        'raw_date_text': raw,
        'location_name': None,
        'city': CITY,
        'price_text': None,
        'price_unit': None,
        'price_note': None,
        'price_details': None,
        'description': desc,
        'registration_link': event_link(title),
        'image_url': event_image(title),
        'contact_info': {'phone': [], 'telegram': [], 'instagram': [], 'other': []},
        'source_messages': [{
            'line_reference': None,
            'source_excerpt': f'{master + " — " if master else ""}{title}',
            'source_message_timestamp': POST_DATE,
        }],
        'confidence': 0.9,
    }


def headline():
    return {
        'title': 'Фестиваль «Сила Солнца» 2026',
        'event_type': 'festival',
        'category': CAT_LABEL['all'],
        'facilitator': None,
        'status': 'scheduled',
        'date_only': '2026-06-18',
        'end_date_only': '2026-06-20',
        'start_time_only': '12:00',
        'end_time_only': None,
        'raw_date_text': '18–20 июня 2026',
        'location_name': None,
        'city': CITY,
        'price_text': 'от ₪750',
        'price_unit': 'person',
        'price_note': None,
        'price_details': [
            '₪500 — ранняя цена (до 30.04)',
            '₪700 — до 30.05',
            '₪750 — до 17.06',
            '₪800 — с 18.06 (на месте)',
            'Дети до 12 лет: ₪250–300 · 12–18 лет: ₪300–350',
        ],
        'description': (
            '3 дня и 2 ночи на берегу Кинерета: 45+ мастер-классов в 3 потоках — йога, '
            'медитация, дыхательные и телесные практики, нейрографика, звукотерапия, '
            'концерт Frisson Trio, церемонии у костра и детская программа.'
        ),
        'registration_link': FESTIVAL_LINK,
        'image_url': POSTER,
        'contact_info': CONTACT,
        'source_messages': [{
            'line_reference': None,
            'source_excerpt': SITE,
            'source_message_timestamp': POST_DATE,
        }],
        'confidence': 0.95,
    }


def main():
    events = [headline()]
    events += [make_workshop(*s) for s in SLOTS]
    out = Path(__file__).parent / 'events.json'
    out.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Wrote {len(events)} events → {out}')


if __name__ == '__main__':
    main()
