"""Reusable CSS/JS/HTML fragments for tracker dashboard reports."""

RED_FLAGS_CSS = """
.alert-bar{background:rgba(229,72,77,0.08);border:1px solid rgba(229,72,77,0.3);border-radius:8px;padding:12px 16px;margin-bottom:16px}
.alert-bar ul{margin:6px 0 0 18px;color:var(--text);font-size:12px}
.alert-bar .title{color:var(--bad);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.06em}
.threat-banner{background:rgba(232,162,59,0.08);border-bottom:1px solid rgba(232,162,59,0.25);padding:10px 20px;font-size:13px;color:var(--text)}
.threat-banner b{color:var(--warn)}
.guild-banner{background:rgba(63,182,139,0.06);border-bottom:1px solid rgba(63,182,139,0.2);padding:10px 20px;font-size:13px;color:var(--text)}
.col-advanced{display:none}
.table-toolbar{display:flex;justify-content:flex-end;margin-bottom:10px}
.table-toolbar button{background:var(--panel-2);border:1px solid var(--border);color:var(--muted);padding:6px 12px;border-radius:6px;cursor:pointer;font-size:11px}
.table-toolbar button:hover{color:var(--text);border-color:var(--border-2)}
.multiples-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:12px}
.multiple-card{background:var(--panel-2);border:1px solid var(--border);border-radius:8px;padding:10px}
.multiple-card h4{font-size:11px;color:var(--muted);margin-bottom:6px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.multiple-card canvas{width:100%!important;height:100px!important}
.norm-note{color:var(--muted-2);font-size:11px;margin-top:8px}
.coverage-banner{background:rgba(232,162,59,0.08);border:1px solid rgba(232,162,59,0.28);border-radius:8px;padding:12px 16px;margin-bottom:16px;font-size:12px;color:var(--text)}
.coverage-banner .title{color:var(--warn);font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.06em;margin-bottom:6px}
.coverage-banner ul{margin:4px 0 0 18px;color:var(--muted)}
.entrant-badge{display:inline-block;font-size:9px;padding:2px 6px;border-radius:4px;background:rgba(124,92,255,0.15);color:var(--accent-2);margin-left:6px;vertical-align:middle}
.entrant-note{background:rgba(124,92,255,0.06);border:1px solid rgba(124,92,255,0.2);border-radius:8px;padding:10px 14px;margin-bottom:16px;font-size:12px;color:var(--muted)}
.cross-card{background:var(--panel-2);border:1px solid var(--border);border-radius:8px;padding:12px;margin-bottom:8px}
.cross-card .label{color:var(--muted);font-size:10px;text-transform:uppercase;letter-spacing:.06em}
.cross-card .val{font-family:var(--mono);font-size:16px;margin-top:4px;color:var(--accent)}
"""


def red_flags_html(flags: list[str]) -> str:
    if not flags:
        return ""
    items = "".join(f"<li>{f}</li>" for f in flags)
    return f'<div class="alert-bar"><div class="title">Alerts</div><ul>{items}</ul></div>'


def threat_banner_html(text: str, css_class: str = "threat-banner") -> str:
    if not text:
        return ""
    return f'<div class="{css_class}">{text}</div>'


def coverage_banner_html(audit: dict, new_entrants: dict[str, str] | None = None) -> str:
    incomplete = audit.get("incomplete_days") or []
    parts: list[str] = []
    if incomplete:
        days = ", ".join(x["day"] for x in incomplete[:8])
        extra = f" (+{len(incomplete) - 8} more)" if len(incomplete) > 8 else ""
        parts.append(
            f"<li><b>{len(incomplete)} partial scan day(s)</b> excluded from market totals and share charts: "
            f"{days}{extra}. Re-run collect to fill gaps.</li>"
        )
    if new_entrants:
        for name, since in list(new_entrants.items())[:5]:
            parts.append(f"<li><b>{name}</b> tracked since {since} — prior days used smaller market roster.</li>")
    if not parts:
        return ""
    items = "".join(parts)
    return f'<div class="coverage-banner"><div class="title">Data coverage</div><ul>{items}</ul></div>'


def entrant_note_html(new_entrants: dict[str, str], within_days: int = 14) -> str:
    if not new_entrants:
        return ""
    lines = [
        f"<b>{name}</b> added {since}"
        for name, since in sorted(new_entrants.items(), key=lambda x: x[1])
    ]
    return (
        '<div class="entrant-note">Market roster expanded recently — '
        + "; ".join(lines)
        + f". Share % before join used N−{len(new_entrants)} server market.</div>"
    )


TABLE_EXPAND_JS = """
function setupTableExpand(tableId, btnId) {
  const btn = document.getElementById(btnId);
  if (!btn) return;
  let expanded = false;
  btn.addEventListener('click', () => {
    expanded = !expanded;
    document.querySelectorAll(`#${tableId} .col-advanced`).forEach(el => {
      el.style.display = expanded ? '' : 'none';
    });
    btn.textContent = expanded ? 'Show fewer columns' : 'Show all columns';
  });
}
"""


def donut_renorm_js(chart_id: str, labels_var: str, values_var: str, colors_var: str) -> str:
    return f"""
new Chart('{chart_id}',{{type:'doughnut',
  data:{{labels:{labels_var},datasets:[{{data:{values_var},_raw:{values_var},
    backgroundColor:{colors_var},borderWidth:2,borderColor:'#0F1419',hoverOffset:6}}]}},
  options:{{responsive:true,maintainAspectRatio:false,cutout:'62%',
    plugins:{{
      legend:{{position:'bottom',labels:{{color:'#8B98A6',padding:12,font:{{size:11}},usePointStyle:true,pointStyle:'rect',boxWidth:10}},
        onClick(e,item,legend){{
          const c=legend.chart,idx=item.index;
          c.toggleDataVisibility(idx);
          const ds=c.data.datasets[0];
          let total=0; const vis=[];
          ds._raw.forEach((v,i)=>{{if(c.getDataVisibility(i) && v!=null){{total+=v;vis.push({{i,v}});}}}});
          vis.forEach(({{i,v}})=>{{ds.data[i]=total>0?Math.round(v/total*10000)/100:0;}});
          c.update();
        }}
      }},
      tooltip:{{...TIP,callbacks:{{label:c=>{{
        const raw=c.dataset._raw[c.dataIndex];
        const tot=c.dataset._raw.filter((v,i)=>c.chart.getDataVisibility(i)).reduce((a,b)=>a+(b||0),0);
        return ` ${{c.label}}: ${{(raw||0).toLocaleString()}} (${{tot?((raw/tot)*100).toFixed(1):0}}%)`;
      }}}}}}
    }}
  }}
}});
"""


def small_multiples_js(container_id: str, dates_var: str, datasets_var: str, ylabel: str = "") -> str:
    return f"""
(function(){{
  const wrap=document.getElementById('{container_id}');
  const dates={dates_var};
  const datasets={datasets_var};
  if(!wrap||!datasets.length)return;
  let ymax=0;
  datasets.forEach(ds=>{{(ds.data||[]).forEach(v=>{{if(v!=null&&v>ymax)ymax=v;}});}});
  ymax=Math.ceil(ymax*1.05)||1;
  datasets.forEach((ds,i)=>{{
    const card=document.createElement('div');card.className='multiple-card';
    const h=document.createElement('h4');h.textContent=ds.label;card.appendChild(h);
    const cv=document.createElement('canvas');cv.id='mini_'+i;card.appendChild(cv);
    wrap.appendChild(card);
    new Chart(cv,{{type:'line',data:{{labels:dates,datasets:[{{...ds,pointRadius:0,borderWidth:1.5,fill:false}}]}},
      options:{{responsive:true,maintainAspectRatio:false,plugins:{{legend:{{display:false}},tooltip:TIP}},
        scales:{{x:{{display:false}},y:{{min:0,max:ymax,ticks:{{...TICK,maxTicksLimit:4}},grid:GRID}}}}}}
    }});
  }});
}})();
"""
