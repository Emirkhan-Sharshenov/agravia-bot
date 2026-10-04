"""
Прогон QA-набора из ТЗ v2 (раздел 7) против работающего бота.

Запрос идёт по HTTP ровно так, как его шлёт виджет: с историей диалога и
состоянием (state), которое бэкенд вернул в прошлом ответе. Поэтому цепочки
("Я экспонент → Когда заезд?") проверяют настоящее удержание контекста.

Здесь НЕТ ответов бота и подгонки под формулировки: для каждого кейса только
входные реплики и проверяемые свойства (ожидаемая тема, действие, факты,
которых не должно быть выдумано). Итоговую оценку OK / Частично / Ошибка
ставит человек по ответам (см. results.json).

Запуск:
    python qa/run_qa.py [--base URL] [--pause СЕК] [--only 1,5,40-45]

--pause нужен на бесплатном тарифе Groq (8000 токенов/мин на модель): между
репликами делается пауза, чтобы не упираться в rate limit. Результаты
дописываются в results.json по номерам кейсов, поэтому можно перепрогонять
только часть набора (--only).
"""
import argparse
import json
import time
from pathlib import Path

import httpx

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="https://backend-fawn-nine-72.vercel.app")
ap.add_argument("--pause", type=float, default=0.0)
ap.add_argument("--only", default="")
ARGS = ap.parse_args()
BASE = ARGS.base.rstrip("/")


def parse_only(spec: str) -> set[int]:
    out: set[int] = set()
    for part in filter(None, spec.split(",")):
        lo, _, hi = part.partition("-")
        out.update(range(int(lo), int(hi or lo) + 1))
    return out

ANSWER, CLARIFY, ANY = "answer", "clarify", "any"
REG = {"visitor_registration"}
PART = {"participation"}

# (№, группа, [реплики], допустимые intent последней реплики, ожидаемое действие,
#  must_all, must_any, must_not)
CASES = [
    (1, "Даты", ["Когда выставка?"], {"dates"}, ANSWER, ["20", "22"], [], []),
    (2, "Даты", ["Какие даты AGRAVIA 2027?"], {"dates"}, ANSWER, ["20", "22"], [], []),
    (3, "Даты", ["Когда проходит AGRAVIA?"], {"dates"}, ANSWER, ["20", "22"], [], []),
    (4, "Даты", ["В какие дни будет выставка?"], {"dates"}, ANSWER, ["20", "22"], [], []),
    (5, "Даты", ["Подскажите даты проведения"], {"dates"}, ANSWER, ["20", "22"], [], []),
    (6, "Даты", ["А по числам когда?"], {"dates"}, ANSWER, ["20", "22"], [], []),
    (7, "Место", ["Где проходит выставка?"], {"location"}, ANSWER, [], ["крокус", "павильон"], []),
    (8, "Место", ["Какой адрес у AGRAVIA?"], {"location"}, ANSWER, [], ["красногорск", "международная"], []),
    (9, "Место", ["Куда ехать на выставку?"], {"location"}, ANSWER, [], ["крокус", "мякинино"], []),
    (10, "Место", ["Где вы находитесь?"], {"location"}, ANSWER, [], ["крокус", "красногорск"], []),
    (11, "Место", ["В каком павильоне будет AGRAVIA?"], {"location"}, ANSWER, [], ["павильон 3", "павильон №3"], []),
    (12, "Посетитель", ["Как получить билет?"], REG, ANSWER, [], ["agravia.org", "регистрац"], ["бейдж экспонента", "монтаж"]),
    (13, "Посетитель", ["Где взять бейдж?"], REG | {"badge"}, ANSWER, [], [], ["бейдж экспонента", "монтаж"]),
    (14, "Посетитель", ["Как зарегистрироваться?"], REG, ANSWER, [], ["agravia.org", "регистрац"], ["монтаж"]),
    (15, "Посетитель", ["Хочу попасть на выставку, что делать?"], REG, ANSWER, [], ["agravia.org", "регистрац"], ["монтаж"]),
    (16, "Посетитель", ["Как посетить AGRAVIA?"], REG, ANSWER, [], ["agravia.org", "регистрац"], ["монтаж"]),
    (17, "Посетитель", ["Где регистрация для посетителей?"], REG, ANSWER, [], ["agravia.org", "регистрац"], ["монтаж"]),
    (18, "Посетитель", ["Мне нужен билет на выставку"], REG, ANSWER, [], ["agravia.org", "регистрац"], ["монтаж"]),
    (19, "Посетитель", ["Хочу прийти как посетитель"], REG, ANSWER, [], ["agravia.org", "регистрац"], ["монтаж"]),
    (20, "Посетитель", ["А мне куда нажать, чтобы прийти?"], REG, ANY, [], [], ["монтаж"]),
    (21, "Посетитель", ["Как мне попасть внутрь как гостю?"], REG, ANSWER, [], ["agravia.org", "регистрац"], ["монтаж"]),
    (22, "Посетитель", ["Есть ссылка на регистрацию?"], REG, ANSWER, [], ["agravia.org"], ["монтаж"]),
    (23, "Посетитель", ["Нужен пропуск посетителя"], REG, ANSWER, [], ["agravia.org", "регистрац"], ["монтаж"]),
    (24, "Участие", ["Как стать участником?"], PART, ANSWER, [], ["495", "agros", "организатор"], ["руб", "₽"]),
    (25, "Участие", ["Хочу участвовать в выставке"], PART, ANSWER, [], ["495", "agros", "организатор"], ["руб", "₽"]),
    (26, "Участие", ["Как выставить стенд?"], PART, ANSWER, [], ["495", "agros", "организатор"], ["руб", "₽"]),
    (27, "Участие", ["Хочу стать экспонентом"], PART, ANSWER, [], ["495", "agros", "организатор"], ["руб", "₽"]),
    (28, "Участие", ["Сколько стоит участие?"], PART, ANSWER, [], ["нет", "организатор"], ["руб", "₽"]),
    (29, "Участие", ["Куда подать заявку на участие?"], PART, ANSWER, [], ["495", "agros", "организатор"], ["руб", "₽"]),
    (30, "Участие", ["Как забронировать стенд?"], PART, ANSWER, [], ["495", "agros", "организатор"], ["руб", "₽"]),
    (31, "Участие", ["Мы компания, хотим выставляться"], PART, ANSWER, [], ["495", "agros", "организатор"], ["руб", "₽"]),
    (32, "Участие", ["С кем связаться по участию?"], PART | {"contact"}, ANSWER, [], ["495", "agros", "организатор"], ["руб", "₽"]),
    (33, "Пропуска", ["Мне нужен пропуск"], {"pass"}, CLARIFY, [], [], []),
    (34, "Пропуска", ["Как получить пропуск?"], {"pass"}, CLARIFY, [], [], []),
    (35, "Пропуска", ["Где оформить пропуск?"], {"pass"}, CLARIFY, [], [], []),
    (36, "Пропуска", ["Мне нужен бейдж"], {"badge", "pass"}, CLARIFY, [], [], []),
    (37, "Пропуска", ["Как получить бейдж экспонента?"], {"pass", "badge"}, ANSWER, [], ["бейдж"], []),
    (38, "Пропуска", ["Нужен монтажный пропуск"], {"pass"}, ANSWER, [], ["монтаж"], []),
    (39, "Пропуска", ["Как получить бейдж экспонента?", "А если я посетитель?"], REG | {"pass", "badge"}, ANSWER, [], ["agravia.org", "регистрац"], ["монтаж", "экспонент"]),
    (40, "Пропуска", ["Нужен монтажный пропуск", "Нет, я про билет, не про монтаж"], REG, ANSWER, [], ["agravia.org", "регистрац"], ["монтаж"]),
    (41, "Монтаж", ["Когда монтаж?"], {"montage"}, ANSWER, [], ["19 января", "17"], []),
    (42, "Монтаж", ["Какие даты монтажа?"], {"montage"}, ANSWER, [], ["19 января", "17"], []),
    (43, "Монтаж", ["Когда начинается застройка?"], {"montage"}, ANSWER, [], ["19 января", "17"], []),
    (44, "Монтаж", ["Когда можно собирать стенд?"], {"montage"}, ANSWER, [], ["19 января", "17"], []),
    (45, "Монтаж", ["Когда демонтаж?"], {"demontage"}, ANSWER, [], ["22 января", "23 января"], []),
    (46, "Монтаж", ["Когда можно разбирать стенд?"], {"demontage"}, ANSWER, [], ["22 января", "23 января"], []),
    (47, "Монтаж", ["До скольки можно работать на монтаже?"], {"montage"}, ANSWER, [], ["19:00"], []),
    (48, "Монтаж", ["Можно приехать на монтаж вечером?"], {"montage", "entry"}, ANSWER, [], ["19:00"], []),
    (49, "Заезд", ["Когда заезд?"], {"entry"}, CLARIFY, [], [], []),
    (50, "Заезд", ["Когда заезжают экспоненты?"], {"entry", "montage"}, ANSWER, [], ["19 января", "10:00"], []),
    (51, "Заезд", ["Когда можно завезти оборудование?"], {"equipment_in"}, ANSWER, [], ["январ"], []),
    (52, "Заезд", ["Как завезти оборудование на стенд?"], {"equipment_in"}, ANSWER, [], ["письм", "прр", "пропуск"], []),
    (53, "Заезд", ["Когда вывоз оборудования?"], {"equipment_out"}, ANSWER, [], ["22 января", "закрытия"], []),
    (54, "Заезд", ["Какие документы нужны для ввоза оборудования?"], {"equipment_in"}, ANSWER, [], ["письм"], []),
    (55, "Заезд", ["Можно ли заехать на машине на территорию?"], {"vehicle_access"}, ANY, [], [], []),
    (56, "Заезд", ["Куда ехать машине на разгрузку?"], {"vehicle_access", "equipment_in"}, ANY, [], [], []),
    (57, "Программа", ["Где посмотреть деловую программу?"], {"business_program"}, ANSWER, [], [], []),
    (58, "Программа", ["Какая программа будет на выставке?"], {"business_program"}, ANSWER, [], [], []),
    (59, "Программа", ["Будут конференции?"], {"business_program"}, ANSWER, [], ["конференц"], []),
    (60, "Программа", ["Где расписание мероприятий?"], {"business_program"}, ANY, [], [], []),
    (61, "Программа", ["Что будет по деловой программе?"], {"business_program"}, ANSWER, [], [], []),
    (62, "Программа", ["Во сколько начинаются мероприятия?"], {"business_program"}, ANY, [], [], []),
    (63, "Кабинет", ["Где личный кабинет?"], {"cabinet"}, ANY, [], [], []),
    (64, "Кабинет", ["Как войти в личный кабинет?"], {"cabinet"}, ANY, [], [], []),
    (65, "Кабинет", ["Не могу найти кабинет участника"], {"cabinet"}, ANY, [], [], []),
    (66, "Кабинет", ["Дайте ссылку на личный кабинет"], {"cabinet"}, ANY, [], [], []),
    (67, "Кабинет", ["Где кабинет экспонента?"], {"cabinet"}, ANY, [], [], []),
    (68, "Контакты", ["Как связаться с менеджером?"], {"contact"}, ANSWER, [], ["495", "agros", "@"], []),
    (69, "Контакты", ["Мне нужен человек, а не бот"], {"contact"}, ANSWER, [], ["495", "agros", "@"], []),
    (70, "Контакты", ["Кому написать по участию?"], {"contact"} | PART, ANSWER, [], ["495", "agros", "@"], []),
    (71, "Контакты", ["Можно номер менеджера?"], {"contact"}, ANSWER, [], ["495"], []),
    (72, "Цепочки", ["Я экспонент", "Когда заезд?"], {"entry", "montage"}, ANSWER, [], ["19 января", "10:00"], []),
    (73, "Цепочки", ["Я посетитель", "Как получить пропуск?"], REG, ANSWER, [], ["agravia.org", "регистрац"], ["монтаж"]),
    (74, "Цепочки", ["Хочу участвовать", "А сколько стоит?"], PART, ANSWER, [], ["нет"], ["руб", "₽"]),
    (75, "Цепочки", ["Мне нужен пропуск", "Я экспонент"], {"pass"}, ANSWER, [], ["бейдж", "пропуск"], []),
    (76, "Цепочки", ["Мне нужен пропуск", "Нет, я про билет"], REG, ANSWER, [], ["agravia.org", "регистрац"], ["монтаж"]),
    (77, "Цепочки", ["Когда монтаж?", "А демонтаж?"], {"demontage"}, ANSWER, [], ["22 января", "23 января"], []),
    (78, "Цепочки", ["Как стать участником?", "А куда заявку отправлять?"], PART | {"contact"}, ANSWER, [], ["495", "agros", "организатор"], ["руб", "₽"]),
    (79, "Цепочки", ["Где программа?", "А на второй день что будет?"], {"business_program"}, ANY, [], [], []),
    (80, "Цепочки", ["Я застройщик", "Когда можно заходить на площадку?"], {"entry", "montage"}, ANSWER, [], ["январ"], []),
    (81, "Цепочки", ["Я экспонент", "Когда монтаж?", "А оборудование когда завозить?"], {"equipment_in", "entry", "montage"}, ANSWER, [], ["январ"], []),
    (82, "Устойчивость", ["Расскажи анекдот"], {"offtopic"}, ANY, [], ["agravia"], []),
    (83, "Устойчивость", ["Какая погода будет на выставке?"], {"offtopic", "other"}, ANY, [], [], []),
    (84, "Устойчивость", ["Кто выиграет чемпионат мира?"], {"offtopic"}, ANY, [], ["agravia"], []),
    (85, "Устойчивость", ["Привет"], {"greeting"}, ANY, [], ["помощник", "agravia"], []),
    (86, "Устойчивость", ["Помоги"], {"help"}, CLARIFY, [], [], []),
    (87, "Устойчивость", ["Ничего не понимаю, куда мне нажать"], {"help"}, ANY, [], [], []),
    (88, "Устойчивость", ["asdfgh"], {"gibberish"}, ANY, [], ["переформул"], []),
]

MARKDOWN = ["**", "##", "__", "`"]
MANAGER_FIRST = ["передать его менеджеру", "передам вашу заявку"]


def run_case(client: httpx.Client, turns: list[str]) -> list[dict]:
    history, state, session_id, out = [], None, None, []
    for text in turns:
        t0 = time.time()
        r = client.post(
            f"{BASE}/api/chat",
            json={"session_id": session_id, "message": text, "history": history,
                  "state": state, "debug": True},
            timeout=90,
        )
        r.raise_for_status()
        data = r.json()
        out.append({
            "user": text, "reply": data["reply"], "intent": data.get("intent"), "role": data.get("role"),
            "clarify": data["clarify"], "offer_manager": data["offer_manager"],
            "confidence": data["confidence"], "sec": round(time.time() - t0, 1),
            "errors": data.get("debug") or [],
        })
        if ARGS.pause:
            time.sleep(ARGS.pause)
        session_id, state = data["session_id"], data.get("state")
        history += [{"role": "user", "content": text}, {"role": "assistant", "content": data["reply"]}]
    return out


def auto_check(case, steps) -> list[str]:
    _, _, _, intents, action, must_all, must_any, must_not = case
    last = steps[-1]
    reply = last["reply"].lower()
    issues = []
    if last["intent"] not in intents:
        issues.append(f"intent={last['intent']}, ожидался один из {sorted(intents)}")
    if action == ANSWER and last["clarify"]:
        issues.append("вместо ответа задан уточняющий вопрос")
    if action == CLARIFY and not last["clarify"]:
        issues.append("ожидалось уточнение, дан ответ")
    missing = [s for s in must_all if s not in reply]
    if missing:
        issues.append(f"нет фактов: {missing}")
    if must_any and not any(s in reply for s in must_any):
        issues.append(f"нет ни одного из: {must_any}")
    bad = [s for s in must_not if s in reply]
    if bad:
        issues.append(f"запрещённое содержание: {bad}")
    if any(m in step["reply"] for step in steps for m in MARKDOWN):
        issues.append("Markdown-артефакты в ответе")
    if len(last["reply"]) > 700:
        issues.append(f"слишком длинный ответ ({len(last['reply'])} симв.)")
    return issues


def main():
    out = Path(__file__).parent / "results.json"
    previous = {r["n"]: r for r in json.loads(out.read_text(encoding="utf-8"))} if out.exists() else {}
    only = parse_only(ARGS.only)
    results = []
    with httpx.Client() as client:
        for case in CASES:
            n, group, turns = case[0], case[1], case[2]
            if only and n not in only:
                if n in previous:
                    results.append(previous[n])
                continue
            try:
                steps = run_case(client, turns)
                issues = auto_check(case, steps)
            except Exception as exc:  # фиксируем и идём дальше
                steps, issues = [], [f"ошибка запроса: {exc!r}"]
            results.append({"n": n, "group": group, "turns": turns, "steps": steps, "auto_issues": issues})
            flag = "ok " if not issues else "!! "
            last = steps[-1]["reply"].replace("\n", " ")[:110] if steps else "-"
            print(f"{flag}#{n:<3} {' → '.join(turns)[:60]:<60} | {last}")
            for i in issues:
                print(f"      · {i}")
            for step in steps:
                for e in step.get("errors", []):
                    print(f"      ! {e[:160]}")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    bad = sum(1 for r in results if r["auto_issues"])
    print(f"\nавто-флаги: {bad} из {len(results)}; подробности — {out}")


if __name__ == "__main__":
    main()
