"""
Точечная проверка сценариев из обратной связи Егора (2026-10) против живого бота.
Запрос идёт как у виджета: с историей и state. Печатает ответы для ручной оценки.

    python qa/feedback_check.py [--base URL] [--pause СЕК]
"""
import argparse
import time

import httpx

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="https://backend-fawn-nine-72.vercel.app")
ap.add_argument("--pause", type=float, default=12.0)
ARGS = ap.parse_args()

CHAINS = [
    # 1. одинаковая польза от похожих формулировок
    ["Когда выставка?"], ["Где проходит выставка?"], ["Какой адрес AGRAVIA?"],
    ["Хочу стать экспонентом"], ["Как выставить стенд?"], ["Как забронировать стенд?"],
    # 2. роль уже названа
    ["Как получить бейдж экспонента?"],
    ["Я экспонент", "Сколько стоит участие?"],
    ["Как получить билет?", "А как получить бейдж?"],
    # подтверждённые факты
    ["Нужно ли регистрироваться отдельно на iAGRI?"],
    ["Кто победил в конкурсе Лучший продукт?"],
    # кейсы QA, не проверенные из-за лимита
    ["Нужен монтажный пропуск"], ["Когда можно собирать стенд?"],
    ["Куда ехать машине на разгрузку?"], ["Где посмотреть деловую программу?"],
    ["Во сколько начинаются мероприятия?"], ["Как войти в личный кабинет?"],
    ["Дайте ссылку на личный кабинет"], ["Как связаться с менеджером?"],
    ["Мне нужен человек, а не бот"], ["Можно номер менеджера?"],
    ["Я экспонент", "Когда монтаж?", "А оборудование когда завозить?"],
]

with httpx.Client() as client:
    for turns in CHAINS:
        history, state, sid = [], None, None
        print("─" * 100)
        for text in turns:
            r = client.post(
                f"{ARGS.base}/api/chat",
                json={"session_id": sid, "message": text, "history": history, "state": state, "debug": True},
                timeout=90,
            ).json()
            sid, state = r["session_id"], r.get("state")
            history += [{"role": "user", "content": text}, {"role": "assistant", "content": r["reply"]}]
            errs = " | ".join(e[:90] for e in (r.get("debug") or []))
            print(f"▶ {text}\n   [{r['intent']}/{r['role']} clarify={r['clarify']} mgr={r['offer_manager']}]"
                  f"\n   {r['reply']}" + (f"\n   !! {errs}" if errs else ""), flush=True)
            time.sleep(ARGS.pause)
