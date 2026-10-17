"""日次ダッシュボード(単体HTML)を生成。GitHub Pagesで公開する。"""
import json

import pandas as pd

from .report import comment

COLS = ["code", "name", "score", "s_short", "s_trend", "s_volume", "s_margin", "short_pct", "short_delta_pp",
        "short_delta_rate", "n_up", "close", "ma5", "ma20", "day_chg", "vol_ratio", "buy_chg_pct",
        "main_holders", "flag_buyback_start", "flag_buyback_turn", "type_sell_continue", "type_buyback",
        "type_squeeze", "exclude_reason", "comment"]


def build(date, sc: pd.DataFrame, rk: dict, hist, path):
    d = sc.copy()
    d["comment"] = [comment(r, hist) for r in d.itertuples()]
    ids = {k: v["code"].tolist() for k, v in rk.items()}
    payload = {"date": str(date), "ids": ids,
               "rows": json.loads(d[COLS].to_json(orient="records", force_ascii=False))}
    html = TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False).replace("</", "<\\/"))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


TEMPLATE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>機関空売りスクリーナー</title>
<style>
:root{--bg:#f6f7f9;--card:#fff;--tx:#1d2330;--mut:#6b7385;--ln:#e3e6ec;--ac:#1f5fd6;--up:#c62828;--dn:#1b7f3b}
@media(prefers-color-scheme:dark){:root{--bg:#10131a;--card:#181c26;--tx:#e8ebf2;--mut:#98a0b3;--ln:#2a3040;--ac:#6ea0ff;--up:#ff7a7a;--dn:#5fd08a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);font:14px/1.5 system-ui,"Hiragino Sans","Yu Gothic",sans-serif}
header{padding:14px 16px;border-bottom:1px solid var(--ln);background:var(--card);position:sticky;top:0;z-index:2}
h1{font-size:16px;margin:0}.sub{color:var(--mut);font-size:12px}
nav{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
nav button{border:1px solid var(--ln);background:var(--card);color:var(--tx);padding:6px 12px;border-radius:99px;cursor:pointer;font:inherit}
nav button.on{background:var(--ac);color:#fff;border-color:var(--ac)}
input{margin-top:10px;width:100%;max-width:340px;padding:7px 10px;border:1px solid var(--ln);border-radius:8px;background:var(--card);color:var(--tx);font:inherit}
main{padding:12px 16px 40px}.note{color:var(--mut);font-size:12px;margin:0 0 10px}
.wrap{overflow-x:auto;background:var(--card);border:1px solid var(--ln);border-radius:10px}
table{border-collapse:collapse;width:100%;min-width:760px}
th,td{padding:8px 10px;border-bottom:1px solid var(--ln);text-align:right;white-space:nowrap}
th{cursor:pointer;color:var(--mut);font-weight:600;font-size:12px;position:sticky;top:0;background:var(--card)}
td.l,th.l{text-align:left}tr.row{cursor:pointer}tr.row:hover{background:rgba(120,140,190,.08)}
.up{color:var(--up)}.dn{color:var(--dn)}
.tag{display:inline-block;font-size:11px;padding:1px 7px;border-radius:99px;margin-right:4px;border:1px solid var(--ln);color:var(--mut)}
.tag.hot{color:var(--up);border-color:var(--up)}.tag.ok{color:var(--dn);border-color:var(--dn)}
tr.cm td{white-space:pre-line;text-align:left;background:rgba(120,140,190,.06);color:var(--tx)}
</style></head><body>
<header><h1>機関空売り・需給スクリーナー</h1><div class="sub" id="sub"></div>
<nav id="nav"></nav><input id="q" placeholder="銘柄コード・名前で検索"></header>
<main><p class="note" id="note"></p><div class="wrap"><table id="t"></table></div></main>
<script>
const D=__DATA__;
const byCode=Object.fromEntries(D.rows.map(r=>[r.code,r]));
const tabs=[
 ["sell","売り継続",D.ids.sell.map(c=>byCode[c]),"空売り増加×下落トレンド×出来高×信用。点数順。"],
 ["buyback","買い戻し",D.ids.buyback.map(c=>byCode[c]),"空売り残高が減少した銘柄(減少率順)。「転換」は株価上昇+出来高増も伴うもの。"],
 ["squeeze","踏み上げ候補",D.ids.squeeze.map(c=>byCode[c]),"空売り高水準×株価上昇×出来高急増×5日線・20日線の上。"],
 ["all","全銘柄",D.rows,"除外・警告の銘柄も含む。列見出しで並べ替え。"]];
let cur="sell",sortKey=null,sortDir=-1;
const f=(v,d=2)=>v==null||isNaN(v)?"-":Number(v).toFixed(d);
const pc=(v,d=1)=>v==null?"-":(v*100).toFixed(d)+"%";
const sg=v=>v==null?"":(v>0?"up":v<0?"dn":"");
const cols=[
 ["code","コード",r=>r.code,"l"],["name","銘柄名",r=>r.name,"l"],["score","総合点",r=>r.score],
 ["short_pct","空売り合計%",r=>f(r.short_pct)],
 ["short_delta_pp","増減pp",r=>`<span class="${sg(r.short_delta_pp)}">${r.short_delta_pp>0?"+":""}${f(r.short_delta_pp)}</span>`],
 ["close","株価",r=>f(r.close,0)],["ma5","5日線",r=>f(r.ma5,0)],["ma20","20日線",r=>f(r.ma20,0)],
 ["day_chg","前日比",r=>`<span class="${sg(r.day_chg)}">${pc(r.day_chg)}</span>`],
 ["vol_ratio","出来高倍率",r=>f(r.vol_ratio)],["buy_chg_pct","信用買い残増減",r=>pc(r.buy_chg_pct)],
 ["main_holders","主要空売り機関",r=>r.main_holders||"-","l"],
 ["flag","判定",r=>[
   r.type_sell_continue&&'<span class="tag hot">売り継続</span>',
   r.flag_buyback_turn&&'<span class="tag ok">買い戻し転換</span>',
   r.flag_buyback_start&&!r.flag_buyback_turn&&'<span class="tag ok">買い戻し開始</span>',
   r.type_squeeze&&'<span class="tag hot">踏み上げ</span>',
   r.exclude_reason&&`<span class="tag">${r.exclude_reason}</span>`].filter(Boolean).join(""),"l"]];
function render(){
 const t=tabs.find(x=>x[0]===cur);let rows=t[2].slice();
 const q=document.getElementById("q").value.trim();
 if(q)rows=D.rows.filter(r=>(r.code+r.name).includes(q));
 if(sortKey)rows.sort((a,b)=>((a[sortKey]??-1e18)-(b[sortKey]??-1e18))*sortDir||0);
 document.getElementById("note").textContent=(q?`検索結果 ${rows.length}件`:t[3]);
 let h="<tr><th>#</th>"+cols.map(c=>`<th class="${c[3]||""}" onclick="srt('${c[0]}')">${c[1]}</th>`).join("")+"</tr>";
 rows.forEach((r,i)=>{h+=`<tr class="row" onclick="tg(${i})"><td>${i+1}</td>`+cols.map(c=>`<td class="${c[3]||""}">${c[2](r)}</td>`).join("")+`</tr><tr class="cm" id="c${i}" hidden><td colspan="${cols.length+1}">${r.comment}</td></tr>`});
 document.getElementById("t").innerHTML=rows.length?h:"<tr><td class='l'>該当なし</td></tr>";
}
function tg(i){const e=document.getElementById("c"+i);e.hidden=!e.hidden}
function srt(k){if(!(k in D.rows[0]))return;sortDir=sortKey===k?-sortDir:-1;sortKey=k;render()}
document.getElementById("sub").textContent="データ日: "+D.date+" / 行をタップでコメント表示";
document.getElementById("nav").innerHTML=tabs.map(t=>`<button id="b_${t[0]}" onclick="cur='${t[0]}';sortKey=null;sync();render()">${t[1]} (${t[2].length})</button>`).join("");
function sync(){tabs.forEach(t=>document.getElementById("b_"+t[0]).classList.toggle("on",t[0]===cur))}
document.getElementById("q").oninput=render;sync();render();
</script></body></html>
"""
