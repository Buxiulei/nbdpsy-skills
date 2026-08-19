#!/usr/bin/env python3
"""把视频 / 播客笔记发布到小红书（经 nbdpsy-api，纯 REST）——**视频线的唯一脚本层**。

图文走 `publish_note.py`；视频/播客走这里。两者共用同一套解析、鉴权、轮询代码
（本脚本 import publish_note 复用），**三道闸门的实现也同源**——闸门 A/C 的函数体 2026-08-14
搬进了 `publish_note.py`（图文线此前裸奔：闸门只有视频线有代码），本文件只做同名绑定：

  闸门 A · 封面产出凭证：`--cover` **必填**，且同名 `cover-*.meta.json` 回执必须过校验
      （来源=gen_images 的 job/session 或运营明确认可；提示词摘要里要有色值与具名版式；
      凭证比封面图旧＝脱钩，同样拒发）。
      ⛔ 没有凭证一律拒发——命名约定挡不住自造文件（2026-08-14 事故：自写 HTML 渲出
      合规命名的 cover-*.jpg 就绕过了「封面按 §2-b 走」这句话），凭证能。
  闸门 B · 无 job 不发：本脚本每次动作都建一条 server 侧 job（发布=publish-jobs、
      补封面=note-components），**⛔ 手搓 payload 直调 API 是违规路径**。
  闸门 C · 台账先行 + 回读差集：提交前先往 `publish-ledger.md` 落一行「意图」，
      拿到终态回执后回填「实际」并算出**差集**（意图有、实际没有的那些）。
      **差集非空 = 本批不许报完成**（exit 3）；差集空才 `- [x]`。
      fresh agent 接手第一件事：`--ledger-check`。
      台账从稿件/媒体目录推导（或显式 `--ledger`，或 cwd 里**已存在**那份），⛔ 任何时候都不新建；
      差集**合并事后补救**：`--fix-cover` 成功会把 note-components 任务号登记进那一行，
      `--recheck` 拿它回服务端读 applied.cover，真 true 才把 cover 这项算达成。

用法：
    # 发布（意图从 post-NN.md 读：title / 「## 发布文案」正文 / 标签行→topics）
    python3 publish_video.py --note post-01.md --account 6 --video cam-2.mp4 --cover cover-2.jpg \
        [--collection-id ID --collection-name 名] [--activity-id ID] [--note-purpose 文案]
        [--schedule 2026-08-15T09:00:00+08:00] [--ledger 路径] [--dry-run]
    # 不用 md 时（直接给标题正文；正文末尾的 #标签 行照样自动拆成 topics）
    python3 publish_video.py --title "标题" --content-file body.md --account 6 --video a.mp4 --cover c.jpg
    # 播客
    python3 publish_video.py --note post-01.md --account 2 --audio ep1.m4a --cover c.jpg
    # 回执复查 + 重算差集 + 闭环台账（会话断了、或补救之后跑这个）
    # 在稿件/媒体目录里跑即可；别处跑要带 --ledger（或 --note/--video/--cover）——不猜路径也不新建
    python3 publish_video.py --recheck 338 [--ledger 路径]
    # 发布后补封面（发布时 cover=error 的标准补救；note-components 链已真号验过）
    # 成功后会把补救任务号登记进台账那一行，供 --recheck 消费；再跑一次 --recheck 才闭环
    python3 publish_video.py --fix-cover --job 338 --cover cover-2.jpg
    # 读欠账（fresh agent 接手第一件事）
    python3 publish_video.py --ledger-check [路径]
    # 只验封面凭证（出图后、发布前自查）
    python3 publish_video.py --check-cover cover-2.jpg

凭据：与 publish_note.py 同源（NBDPSY_XHS_API_KEY / NBDPSY_XHS_API_BASE，走 nbdpsy_common 三层解析）。

输出契约：stdout 纯 JSON。exit 码**五态，别混**：
    0 = published 且差集为空（真闭环，才可以报完成）
    1 = failed / canceled（真失败，或提交前就被闸门拦下）
    2 = 未到终态 / 状态未知（任务还在服务端跑，⛔ 绝不重发，稍后 --recheck）
    3 = published 但**有欠账**（差集非空：话题没挂上 / 封面 error / 合集没进）——
        台账里那一行仍是 `- [ ]`，补救完再 --recheck 闭环。**这不是成功。**
    4 = `--ledger-check` 专用：**台账文件不存在**（这批还没发过，或发了没落台账）。
        ⚠️ 2026-08-14 修正：以前"没台账"与"全部闭环"回同一个 exit 0——**没台账 ≠ 闭环**，
        那是没有证据，不是没有欠账。

真实契约以 `publish_note.py --manifest` 为准（本文件依据 2026-08-14 manifest v0.24.4 写就）：
publish-jobs 的 video/audio/cover 都收**服务器侧文件路径**（同机 cp 进 server 数据目录，零传输）；
终态白名单 published|failed|canceled（⚠️ 是一个 l 的 canceled）；
note-components 的 cover **只对视频笔记有效**（图文传 cover 直接 422）。
"""
import argparse
import json
import sys
import time
from pathlib import Path

# 同目录 vendored 副本：解析 / 鉴权 / 轮询 / 报错口径全部复用图文那条线，别再写第二份
import publish_note as pn
import nbdpsy_common  # noqa: F401  （publish_note 已 import，这里显式声明依赖关系）

COMPONENT_TERMINAL = {"done", "error", "unknown"}

# ⬇️ 闸门 A（封面产出凭证）与闸门 C（台账 + 回读差集）的实现**已收敛进 `publish_note.py`**
# （2026-08-14：图文线原本裸奔——闸门只在视频线有代码，正是干跑报告 G1/G5/G6 判死的那处）。
# 这里只做同名绑定，两条线共用同一份判据；⛔ 别在本文件里抄第二份实现，两份必然漂移。
COVER_LAYOUTS = pn.COVER_LAYOUTS
COVER_SOURCES = pn.COVER_SOURCES
LEDGER_NAME = pn.LEDGER_NAME
LEDGER_HEADER = pn.LEDGER_HEADER
now_iso = pn.now_iso
cover_meta_path = pn.cover_meta_path
check_cover_receipt = pn.check_cover_receipt          # 六项校验 + 凭证/文件脱钩（mtime）判据
confirm_cover_receipt = pn.confirm_cover_receipt      # 单出确认戳：⛔ 同一个函数，别在这边另写一份
ledger_path = pn.ledger_path
ledger_append = pn.ledger_append
ledger_replace = pn.ledger_replace
ledger_find_by_job = pn.ledger_find_by_job
ledger_row = pn.ledger_row
ledger_check = pn.ledger_check                        # 台账不存在 = exit 4（⛔ 不与全闭环同绿）
ledger_remedies = pn.ledger_remedies                  # 台账行里登记的补救任务号（索引，不是凭据）
ledger_set_remedies = pn.ledger_set_remedies
verify_remedies = pn.verify_remedies                  # 回服务端验 applied：只有 true 才算数
account_display = pn.account_display                  # 台账账号字段只写账号名，⛔ 不写编号
diff_intent_actual = pn.diff_intent_actual
intent_summary = pn.intent_summary
intent_from_view = pn.intent_from_view


# ---------------------------------------------------------------- 发布

def build_intent(args, meta, content, topics, cover_name):
    return {"topics": topics,
            "cover": cover_name,
            "collection": args.collection_name or args.collection_id,
            "quote": args.quoted_note_id or args.related_counselor
                     or meta.get("related_counselor"),
            "activity": args.activity_id}


def do_publish(args, api_base, key):
    if bool(args.video) == bool(args.audio):
        raise ValueError("--video 与 --audio 二选一（图文请走 publish_note.py）")
    if not args.cover:
        raise ValueError(
            "⛔ --cover 必填：视频封面必须走工序③ 出的封面，不许用平台自动截的第一帧。\n"
            "  （2026-08-14 事故：三条片子发出去用的都是平台截的空白首帧，老板当场发现）")
    receipt = check_cover_receipt(args.cover)      # 闸门 A：不过直接抛，绝不带着往下走

    if args.note:
        meta, body = pn.parse_frontmatter(args.note.read_text(encoding="utf-8"))
        title = str(meta.get("title") or "").strip()
        content, topics = pn.split_content_topics(pn.extract_publish_text(body), meta)
        what = args.note.name
    else:
        if not (args.title and args.content_file):
            raise ValueError("没给 --note 时必须给 --title 与 --content-file")
        meta = {}
        title = args.title.strip()
        content, topics = pn.split_content_topics(
            args.content_file.read_text(encoding="utf-8").strip(), {})
        what = args.content_file.name
    if args.topics:
        topics = args.topics
    if not title:
        raise ValueError("缺 title（frontmatter 的 title 或 --title）")
    # ⚠️ 话题必须**单传 topics 字段**才成话题实体；只写在正文里是纯文本
    # （job337 实证：视频直调裸奔，5 个标签全成了正文里的死字符，topics_applied 空）
    if not topics:
        print("⚠ 没有话题：正文末尾没有 #标签 行、frontmatter 也没 hashtags——"
              "视频笔记没话题＝丢掉一整条搜索入口，确认是有意为之", file=sys.stderr)

    media_kind = "video" if args.video else "audio"
    extras = {}
    for k, v in (("collection_id", args.collection_id), ("collection_name", args.collection_name),
                 ("quoted_note_id", args.quoted_note_id), ("activity_id", args.activity_id),
                 ("related_counselor", args.related_counselor or meta.get("related_counselor")),
                 ("note_purpose", args.note_purpose or meta.get("note_purpose"))):
        if v not in (None, ""):
            extras[k] = v
    warnings = pn.build_warnings(title, content, topics, [], media_kind)
    for w in warnings:
        print(f"⚠ {w}", file=sys.stderr)

    intent = build_intent(args, meta, content, topics, args.cover.name)
    if args.dry_run:
        print(json.dumps({"outcome": "dry_run", "title": title, "content_chars": len(content),
                          "topics": topics, "media_kind": media_kind,
                          "media": str(args.video or args.audio), "cover": str(args.cover),
                          "cover_receipt": receipt, "extras": extras,
                          "intent": intent_summary(intent), "warnings": warnings},
                         ensure_ascii=False, indent=2))
        return 0

    account_id, account_label, acc_warn = pn.resolve_account(api_base, key, args.account)
    if acc_warn:
        print(f"⚠ {acc_warn}", file=sys.stderr)

    lp = ledger_path(args, args.note or args.content_file)
    ts = now_iso()
    who = account_display(api_base, key, account_id, account_label)
    pending_row = ledger_row(False, ts, what, who, "待回执", intent_summary(intent),
                             "—", "待回执")
    ledger_append(lp, pending_row)          # 闸门 C：**提交之前**先落意图行

    payload = {"account_id": account_id, "title": title, "content": content,
               "topics": topics, **extras}
    payload[media_kind] = pn.stage_media(args.video or args.audio, media_kind)
    payload["cover"] = pn.stage_media(args.cover, "cover")
    if args.schedule:
        payload["schedule_time"] = args.schedule

    print(f"提交发布：{what} → {who}（{media_kind} {(args.video or args.audio).name}）…",
          file=sys.stderr)
    job_id = None
    try:
        resp = pn.send_request("POST", f"{api_base}/api/publish-jobs", key, payload, timeout=180)
        if resp.status_code >= 400:
            raise ValueError(pn.api_error(resp))
        job_id = resp.json()["job_id"]
        print(f"  已入队 job_id={job_id}", file=sys.stderr)
        row = ledger_row(False, ts, what, who, job_id, intent_summary(intent), "—", "待回执")
        ledger_replace(lp, pending_row, row)

        if args.no_wait:
            print(json.dumps({"outcome": "pending", "job_id": job_id, "ledger": str(lp),
                              "hint": f"稍后 --recheck {job_id} 回读并闭环台账"},
                             ensure_ascii=False))
            return 2
        # 视频 publishing 阶段可长达十几分钟（11 分钟级视频实测），别当卡死
        view = pn.poll_job(api_base, key, job_id, timeout=args.wait_timeout, interval=15)
    except Exception as e:
        msg = pn.sandbox_hint(e)
        row = ledger_row(False, ts, what, who, job_id or "待回执", intent_summary(intent),
                         "状态未知", f"状态未知({msg[:80]})")
        ledger_replace(lp, pending_row, row)
        print(json.dumps({"outcome": "unknown", "job_id": job_id, "ledger": str(lp),
                          "error": msg,
                          "hint": (f"任务可能已在服务端跑，⛔ 绝不重发：--recheck {job_id} 复查"
                                   if job_id else "提交前失败，修因后重来")},
                         ensure_ascii=False))
        return 2 if job_id else 1

    return finish(view, intent, lp, pending_row_or_job=job_id, ts=ts, what=what, who=who,
                  intent_txt=intent_summary(intent), api_base=api_base, key=key)


def finish(view, intent, lp, pending_row_or_job, ts, what, who, intent_txt,
           api_base=None, key=None):
    jid = view.get("job_id") or pending_row_or_job
    old = ledger_find_by_job(lp, jid)
    # 闭环判据 = 发布回执 ⊕ 事后补救任务的终态。补救任务号从台账那行读（服务端没有按 note 列
    # 补救任务的端点），但**生效与否一律回服务端问**——⛔ 不拿台账里那句登记当凭据。
    remedies = ledger_remedies(old)
    verified = verify_remedies(api_base, key, remedies) if (api_base and remedies) else {}
    actual, gap, ngap = diff_intent_actual(view, intent, verified)
    status = view.get("status")
    closed = (status == "published" and ngap == 0)
    row = ledger_row(closed, ts, what, who, jid, intent_txt, actual, gap, remedies)
    if old:
        ledger_replace(lp, old, row)
    else:
        ledger_append(lp, row)

    out = pn.job_brief(view)
    out.update({"ledger": str(lp), "intent": intent_txt, "actual": actual, "gap": gap,
                "gap_count": ngap})
    if remedies:
        out["remedies"] = {"recorded": remedies, "verified": verified}
    if status in ("failed", "canceled"):
        code = 1
    elif status != "published":
        out["hint"] = f"未到终态，⛔ 别重发：稍后 --recheck {view.get('job_id')}"
        code = 2
    elif ngap:
        out["hint"] = ("**published 但有欠账，这不是成功**：按差集逐项补救"
                       "（cover=FAIL 走 --fix-cover；话题缺失换词重挂），"
                       f"补完 --recheck {view.get('job_id')} 闭环台账")
        code = 3
    else:
        code = 0
    print(json.dumps(out, ensure_ascii=False))
    return code


# ---------------------------------------------------------------- 复查 / 补封面

def do_recheck(args, api_base, key):
    # ⛔ 先定位台账再打网络：定位不到 / 台账不存在就报错指路，**绝不新建**
    # （2026-08-16 事故：旧代码回落 cwd，在 NBDpsy 仓库根凭空造了一份空台账，
    #  真台账在媒体目录里永远闭不掉——「另起一份」比报错危险得多）。
    lp = ledger_path(args)
    if not lp.exists():
        raise ValueError(
            f"台账不存在：{lp}。--recheck 只回填既有台账、不新建。"
            "① 台账在别处 → 给 `--ledger <台账路径>`（或在稿件目录里跑）；"
            "② 这批压根没落过台账 → 说明发布没走 publish_video.py（手搓 payload 直调不落台账），"
            "先 `publish_note.py --list-jobs` 把已发的 job 捞回来核对，⛔ 别据此报完成。")
    view = pn.poll_job(api_base, key, args.recheck, timeout=0)
    old = ledger_find_by_job(lp, args.recheck)
    intent = intent_from_view(view)
    parts = old.split(" | ") if old else []
    ts = parts[0][6:] if parts else now_iso()
    what = parts[1] if len(parts) > 1 else str(view.get("title") or "—")
    who = account_display(api_base, key, view.get("account_id"),
                          parts[2] if len(parts) > 2 else None)
    intent_txt = parts[4][4:] if len(parts) > 4 else intent_summary(intent)
    return finish(view, intent, lp, args.recheck, ts, what, who, intent_txt,
                  api_base=api_base, key=key)


def record_remedy(args, comp: str, cjob) -> dict:
    """把补救任务号登记回台账那一行——**recheck 靠它才找得到这条补救**（服务端没有按 note
    列补救任务的端点）。登记的是索引不是凭据：翻不翻 `- [x]` 仍由 --recheck 回服务端验 applied。

    🔴 **在入队瞬间调用，⛔ 不等终态**（2026-08-19 事故）：`job_id` 入队就有了，
    而终态要等轮询——**绑在一起，网关一抖就把索引陪葬**，台账从此闭不掉。
    ⚠️ **幂等**：`remedies[comp] = str(cjob)` 是覆盖式赋值，重复写同值无害。

    登记失败只告警不改退出码：封面已经真补上了，为「记账没写成」把成功报成失败更误导人。"""
    if not args.job:
        return {"recorded": False,
                "reason": f"没给 --job，定位不到台账行：手工在那行差集之后补一段 `| 补救: {comp}={cjob} `，"
                          "或带 --job <发布任务号> 重跑本命令（封面补挂是幂等的，已是自定义封面会 "
                          "skipped、零点击零提交）"}
    try:
        lp = ledger_path(args)
    except ValueError as e:
        return {"recorded": False, "reason": str(e)}
    old = ledger_find_by_job(lp, args.job)
    if not old:
        return {"recorded": False, "ledger": str(lp),
                "reason": f"{lp} 里没有 job={args.job} 那一行——台账路径给错了？"
                          "用 `--ledger <台账路径>` 指准再重跑登记（补封面本身已成功，别重跑 --fix-cover，"
                          "每次重跑都是一次真提交）"}
    remedies = ledger_remedies(old)
    remedies[comp] = str(cjob)
    ledger_replace(lp, old, ledger_set_remedies(old, remedies))
    return {"recorded": True, "ledger": str(lp), "remedies": remedies}


def do_fix_cover(args, api_base, key):
    """发布后补封面——发布时 cover=error 的标准补救（两条链页面结构不同，这条已真号验过）。

    ⚠️ 只对视频笔记有效（台账 note_type=video），图文传 cover 直接 422。
    """
    receipt = check_cover_receipt(args.cover)      # 补救也过同一道凭证闸门
    if args.job:
        view = pn.poll_job(api_base, key, args.job, timeout=0)
        account_id, note_id = view.get("account_id"), view.get("note_id")
        if not note_id:
            # 🩸 **这一步 100% 必经，⛔ 不是偶发**（2026-08-19 小红书发布线：job 349、350
            # 连续两次都撞）：发布刚落地时台账里还没有平台 note_id，而补封面要它定位笔记。
            # ⚠️ **⛔ 没做成"自动跑一次 sync"**：`--fix-cover` 的语义是补封面，
            #    顺手改台账文件是另一个动作；而且 note_ops 也要推台账路径——
            #    **在一个刚修完路径推导 bug 的地方再叠一层推导，风险大于省下的那一步**。
            # ⇒ 改成给一条**可直接粘贴的完整命令**（账号 id 从 job 回执里取，⛔ 不留 `<账号>` 让人猜）。
            raise ValueError(
                f"job {args.job} 没有 note_id（台账还没回填平台 id）——"
                f"**发布与补封面之间必须夹一次台账同步**，它幂等、可放心重试：\n"
                f"   python3 note_ops.py --sync-ledger {account_id or '<账号名或ID>'}\n"
                f"   然后原样重跑本条 --fix-cover（补封面是幂等的：已是自定义封面会 skipped）")
    else:
        if not (args.account and args.note_id):
            raise ValueError("--fix-cover 需要 --job <发布任务号>，或 --account + --note-id")
        account_id, _, _ = pn.resolve_account(api_base, key, args.account)
        note_id = args.note_id

    payload = {"note_id": note_id, "cover": pn.stage_media(args.cover, "cover")}
    resp = pn.send_request("POST", f"{api_base}/api/accounts/{account_id}/note-components",
                           key, payload, timeout=120)
    if resp.status_code >= 400:
        raise ValueError(pn.api_error(resp))
    cjob = resp.json()["job_id"]
    print(f"  补封面已入队 job_id={cjob}", file=sys.stderr)

    # 🔴 **入队即登记，⛔ 不等轮询拿到终态**（2026-08-19 咪问首发实炸，小红书发布线转 xhs-server 定位）。
    #
    # 🩸 事故形状：轮询中吃了一个 Cloudflare **502**，脚本报 `outcome: failed` ——
    #    而只读复查 `GET /api/note-components/<cjob>` 是 **status:done / applied.cover:true**，
    #    **任务其实成功了，502 只断了轮询**。次生影响才是真伤：登记没做 ⇒ 台账那一行
    #    不知道该去读哪个 component job ⇒ `--recheck` 只能读发布 job 的原始回执（`cover=error`）
    #    ⇒ **台账永远闭不掉**，而**不看脚本源码的人根本不知道要手工补索引**。
    #
    # 🔴 根因是**把两件事绑在一起**：「登记去哪读」与「读到了什么」。
    #    前者在**入队瞬间就已确定**（server 回执里就有 job_id），后者要等轮询——
    #    绑在一起，**网关一抖就把前者陪葬**。
    # ⇒ 拆开：入队即写索引（`remedies[comp] = cjob` 是覆盖式赋值 ⇒ **重复写同值天然幂等**），
    #   **终态判定仍然只由 `--recheck` 回 server 读**，⛔ 这里不下闭环结论、不会造成假闭环。
    remedy = record_remedy(args, "cover", cjob)

    deadline = time.monotonic() + args.wait_timeout
    cview = {}
    try:
        while True:
            r = pn.send_request("GET", f"{api_base}/api/note-components/{cjob}", key)
            if r.status_code >= 400:
                raise ValueError(pn.api_error(r))
            cview = r.json()
            st = cview.get("status")
            print(f"  note-components {cjob}: {st}", file=sys.stderr)
            if st in COMPONENT_TERMINAL or time.monotonic() >= deadline:
                break
            time.sleep(10)
    except Exception as e:
        # ⚠️ **轮询断了 ≠ 任务失败**：任务在 server 上照跑。⛔ 别裸抛——
        # 裸抛会把已经拿到的 cjob 埋进 traceback，人得去翻栈才知道该 recheck 哪个号。
        print(json.dumps({
            "outcome": "unknown", "component_job_id": cjob, "note_id": note_id,
            "error": f"{type(e).__name__}: {e}", "ledger_remedy": remedy,
            "hint": (f"⚠️ 轮询断了，**任务多半仍在服务端跑完了**——⛔ 绝不重跑 --fix-cover"
                     f"（每次重跑都是一次真提交）。\n"
                     f"   只读复查：GET /api/note-components/{cjob} 看 applied.cover 是不是 true；\n"
                     f"   台账索引**已在入队时写好**，直接 --recheck {args.job or '<发布任务号>'} 闭环"),
        }, ensure_ascii=False))
        return 2

    ok = ((cview.get("applied") or {}).get("cover") is True)
    out = {"outcome": cview.get("status"), "component_job_id": cjob, "note_id": note_id,
           "applied_cover": (cview.get("applied") or {}).get("cover"),
           "reason": cview.get("reason"), "cover_receipt": receipt,
           # ⚠️ 成败都带上：登记是**索引**不是**凭据**，失败时同样要能顺着它去复查
           "ledger_remedy": remedy}
    if ok and args.job:
        out["next"] = f"封面已补上，跑 --recheck {args.job} 把台账那一行闭掉"
    elif not ok:
        out["hint"] = ("applied.cover 不是 true ＝ 没换上（这条产品线的失败是静默的，"
                       "只有 true 才算数）：看 reason/observed 取证，⛔ 别盲目重跑——"
                       "每次重跑都是一次真提交")
    print(json.dumps(out, ensure_ascii=False))
    return 0 if ok else 3


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(
        description="发布视频/播客笔记到小红书（内建封面凭证 / 无 job 不发 / 台账差集三闸门）")
    ap.add_argument("--note", type=Path, help="笔记文件（post-NN.md，含 frontmatter 与「## 发布文案」块）")
    ap.add_argument("--title", help="不用 --note 时的标题")
    ap.add_argument("--content-file", type=Path, help="不用 --note 时的正文文件（末尾 #标签 行自动拆 topics）")
    ap.add_argument("--account", help="小红书账号：数字 id 或账号名/昵称（⛔ 视频不走广播，一稿多号须逐号差异化）")
    ap.add_argument("--video", type=Path, help="视频文件（.mp4/.mov/… 同机自动落进 server 数据目录）")
    ap.add_argument("--audio", type=Path, help="播客音频（.m4a/.mp3/…；时长 10 分钟-2 小时、≤1GB）")
    ap.add_argument("--cover", type=Path, help="封面图（**必填**，须有同名 cover-*.meta.json 产出凭证）")
    ap.add_argument("--topics", nargs="+", help="覆盖话题（默认取正文末尾 #标签 行 / frontmatter hashtags）")
    ap.add_argument("--collection-id", help="加入合集（按稿件 frontmatter 的『议题合集』挂）")
    ap.add_argument("--collection-name", help="合集名（供服务端做已选态比对，带 id 就顺带给）")
    ap.add_argument("--quoted-note-id", help="引用某篇笔记")
    ap.add_argument("--related-counselor", help="关联咨询师姓名（服务端在本账号内推导引用笔记）")
    ap.add_argument("--activity-id", help="关联活动（⛔ 只能发布时挂，事后补不上）")
    ap.add_argument("--note-purpose", help="本篇核心目的")
    ap.add_argument("--schedule", help="定时发布 ISO8601 带时区，如 2026-08-15T09:00:00+08:00")
    ap.add_argument("--ledger", help=f"台账路径（默认 <稿件同目录>/{LEDGER_NAME}）")
    ap.add_argument("--ledger-check", nargs="?", const="", metavar="路径",
                    help="读欠账：列出所有未闭环行（有欠账 exit 3；台账不存在 exit 4，那不是闭环）")
    ap.add_argument("--recheck", type=int, metavar="JOB_ID", help="回读该发布任务、重算差集并闭环台账")
    ap.add_argument("--fix-cover", action="store_true", help="发布后补封面（配 --job 或 --account+--note-id）")
    ap.add_argument("--job", type=int, help="--fix-cover 用：原发布任务号（据它取 account/note_id）")
    ap.add_argument("--note-id", help="--fix-cover 用：平台笔记 id（没有 --job 时给）")
    ap.add_argument("--check-cover", type=Path, metavar="封面", help="只校验封面产出凭证，不发布")
    ap.add_argument("--confirm-cover", type=Path, metavar="封面",
                    help="给已有封面凭证补人工确认戳（配 --confirmed-by 姓名），不发布——"
                         "与 publish_note.py 同一个函数、同一道判据")
    ap.add_argument("--confirmed-by", metavar="姓名",
                    help="--confirm-cover 的确认人：看过这张封面的人签名（⛔ 别代签）")
    ap.add_argument("--no-wait", action="store_true", help="提交后不等终态（稍后 --recheck）")
    ap.add_argument("--wait-timeout", type=float, default=1800,
                    help="轮询上限秒数（默认 1800：视频 publishing 可长达十几分钟）")
    ap.add_argument("--dry-run", action="store_true", help="只打 payload 摘要与凭证校验结果")
    ap.add_argument("--api-base", help="API base（默认凭据 NBDPSY_XHS_API_BASE）")
    args = ap.parse_args()

    if args.ledger_check is not None:
        try:
            p = Path(args.ledger_check) if args.ledger_check else ledger_path(args)
        except ValueError as e:
            # 定位不到台账同样**不是闭环**（exit 4 = 没有证据），⛔ 别回 0
            print(json.dumps({"ledger": None, "exists": False, "open_rows": [],
                              "hint": str(e)}, ensure_ascii=False))
            sys.exit(4)
        sys.exit(ledger_check(p))
    if args.check_cover:
        try:
            print(json.dumps(check_cover_receipt(args.check_cover), ensure_ascii=False, indent=2))
            sys.exit(0)
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            sys.exit(1)
    if args.confirm_cover:
        try:
            print(json.dumps(confirm_cover_receipt(args.confirm_cover, args.confirmed_by),
                             ensure_ascii=False, indent=2))
            sys.exit(0)
        except ValueError as e:
            print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
            sys.exit(1)

    key = nbdpsy_common.get_secret(nbdpsy_common.XHS_API_KEY)
    if not key:
        print(f"MISSING:{nbdpsy_common.XHS_API_KEY} 找管理员要「运营接入配置包」，"
              "secret import 导入后重试", file=sys.stderr)
        sys.exit(1)
    api_base = (args.api_base or nbdpsy_common.xhs_api_base()).rstrip("/")

    try:
        if args.recheck is not None:
            sys.exit(do_recheck(args, api_base, key))
        if args.fix_cover:
            if not args.cover:
                raise ValueError("--fix-cover 必须给 --cover")
            sys.exit(do_fix_cover(args, api_base, key))
        if not args.account:
            ap.error("发布需要 --account（或改用 --recheck / --ledger-check / --check-cover）")
        sys.exit(do_publish(args, api_base, key))
    except Exception as e:
        msg = pn.sandbox_hint(e)
        print(f"  → 失败: {msg}", file=sys.stderr)
        print(json.dumps({"outcome": "failed", "error": msg}, ensure_ascii=False))
        sys.exit(1)


if __name__ == "__main__":
    main()
