var e=e=>{switch(e){case`index`:return`@startuml
title "Wave Management Bot — whole-system landscape"
left to right direction

hide stereotype
skinparam ranksep 60
skinparam nodesep 30
skinparam {
  arrowFontSize 10
  defaultTextAlignment center
  wrapWidth 200
  maxMessageSize 100
  shadowing false
}

skinparam person<<Staff>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam person<<Viewer>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam rectangle<<Logistics>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam rectangle<<Supervisor>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam rectangle<<Discord>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam rectangle<<Edge>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam rectangle<<Bot>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam rectangle<<Tunnel>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam database<<MainDb>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam queue<<DmQueueDb>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam rectangle<<Trackers>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam rectangle<<Flask>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam database<<JsonFiles>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
person "==Staff member\\n\\nDrop-map staff across the 3 guilds — earn points, get strikes & rewards" <<Staff>> as Staff
person "==Hub viewer\\n\\nStaff member viewing the leaderboards in a browser" <<Viewer>> as Viewer
rectangle "==Wave Logistics Bot\\n\\nSibling bot on the same machine" <<Logistics>> as Logistics
rectangle "==staff_hub_serve.py\\n\\nSupervisor" <<Supervisor>> as Supervisor
rectangle "==Discord\\n\\ndiscord.py gateway across 3 guilds" <<Discord>> as Discord
rectangle "==Cloudflare Pages\\n\\nEdge gate (two sites)" <<Edge>> as Edge
rectangle "==Wave Management Bot\\n<size:10>[Python / discord.py]</size>\\n\\nThe Discord staff-management bot" <<Bot>> as Bot
rectangle "==cloudflared tunnel\\n\\nQuick tunnel" <<Tunnel>> as Tunnel
database "==bot_database.db\\n<size:10>[SQLite · WAL · async pool]</size>\\n\\nSingle source of truth" <<MainDb>> as MainDb
queue "==dm_shared_queue.db\\n<size:10>[SQLite on C:/Desktop]</size>\\n\\nCross-bot DM queue" <<DmQueueDb>> as DmQueueDb
rectangle "==command-trackers/\\n\\nData trackers shelled out to" <<Trackers>> as Trackers
rectangle "==web_api.py\\n\\nFlask origin @ 127.0.0.1:5000" <<Flask>> as Flask
database "==website/data/*.json\\n\\nBot-built payloads" <<JsonFiles>> as JsonFiles

Staff .[#8D8D8D,thickness=2].> Discord : <color:#8D8D8D>runs > commands
Viewer .[#8D8D8D,thickness=2].> Edge : <color:#8D8D8D>opens hub in browser
Discord .[#8D8D8D,thickness=2].> Bot : <color:#8D8D8D>gateway events
Bot .[#8D8D8D,thickness=2].> Discord : <color:#8D8D8D>[...]
Bot .[#8D8D8D,thickness=2].> MainDb : <color:#8D8D8D>reads / writes state
Bot .[#8D8D8D,thickness=2].> DmQueueDb : <color:#8D8D8D>enqueues every user.send()
Bot .[#8D8D8D,thickness=2].> Trackers : <color:#8D8D8D>shells out to scripts
Bot .[#8D8D8D,thickness=2].> JsonFiles : <color:#8D8D8D>writes per-page JSON
DmQueueDb .[#8D8D8D,thickness=2].> Bot : <color:#8D8D8D>worker claims & delivers
Logistics .[#8D8D8D,thickness=2].> MainDb : <color:#8D8D8D>feeds loot/surge queue codes
Logistics .[#8D8D8D,thickness=2].> DmQueueDb : <color:#8D8D8D>shares the queue
Flask .[#8D8D8D,thickness=2].> JsonFiles : <color:#8D8D8D>serves at /api/<key>
Supervisor .[#8D8D8D,thickness=2].> Flask : <color:#8D8D8D>runs & restarts
Tunnel .[#8D8D8D,thickness=2].> Flask : <color:#8D8D8D>proxies :5000
Supervisor .[#8D8D8D,thickness=2].> Tunnel : <color:#8D8D8D>runs & rewrites URL
Supervisor .[#8D8D8D,thickness=2].> Edge : <color:#8D8D8D>wrangler deploys workers
Edge .[#8D8D8D,thickness=2].> Tunnel : <color:#8D8D8D>proxies with X-API-Key
@enduml
`;case`view_na89us`:return`@startuml
title "Inside the bot — main, cogs, tasks, core"
top to bottom direction

hide stereotype
skinparam ranksep 60
skinparam nodesep 30
skinparam {
  arrowFontSize 10
  defaultTextAlignment center
  wrapWidth 200
  maxMessageSize 100
  shadowing false
}

skinparam rectangle<<Discord>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam queue<<DmQueueDb>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam rectangle<<BotMain>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam rectangle<<BotCogs>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam rectangle<<BotTasks>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam rectangle<<Trackers>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam rectangle<<BotCore>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam database<<MainDb>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam database<<JsonFiles>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
rectangle "==Discord\\n\\ndiscord.py gateway across 3 guilds" <<Discord>> as Discord
queue "==dm_shared_queue.db\\n<size:10>[SQLite on C:/Desktop]</size>\\n\\nCross-bot DM queue" <<DmQueueDb>> as DmQueueDb
rectangle "Wave Management Bot" <<Bot>> as Bot {
  skinparam RectangleBorderColor<<Bot>> #3b82f6
  skinparam RectangleFontColor<<Bot>> #3b82f6
  skinparam RectangleBorderStyle<<Bot>> dashed

  rectangle "==main.py\\n\\nEntry point" <<BotMain>> as BotMain
  rectangle "==commands/ cogs\\n\\nGame & admin systems" <<BotCogs>> as BotCogs
  rectangle "==tasks/ background loops\\n\\nScheduled jobs & queues" <<BotTasks>> as BotTasks
  rectangle "==core/ helpers\\n\\nShared helpers & config" <<BotCore>> as BotCore
}
rectangle "==command-trackers/\\n\\nData trackers shelled out to" <<Trackers>> as Trackers
database "==bot_database.db\\n<size:10>[SQLite · WAL · async pool]</size>\\n\\nSingle source of truth" <<MainDb>> as MainDb
database "==website/data/*.json\\n\\nBot-built payloads" <<JsonFiles>> as JsonFiles

Discord .[#8D8D8D,thickness=2].> BotMain : <color:#8D8D8D>gateway events
DmQueueDb .[#8D8D8D,thickness=2].> BotMain : <color:#8D8D8D>worker claims & delivers
BotMain .[#8D8D8D,thickness=2].> BotCogs : <color:#8D8D8D>loads & dispatches
BotMain .[#8D8D8D,thickness=2].> BotTasks : <color:#8D8D8D>starts loops
BotCogs .[#8D8D8D,thickness=2].> BotCore : <color:#8D8D8D>uses helpers
BotTasks .[#8D8D8D,thickness=2].> BotCore : <color:#8D8D8D>uses helpers
BotMain .[#8D8D8D,thickness=2].> DmQueueDb : <color:#8D8D8D>enqueues every user.send()
BotCogs .[#8D8D8D,thickness=2].> Discord : <color:#8D8D8D>replies, roles, embeds
BotCogs .[#8D8D8D,thickness=2].> MainDb : <color:#8D8D8D>reads / writes state
BotCogs .[#8D8D8D,thickness=2].> Trackers : <color:#8D8D8D>shells out to scripts
BotTasks .[#8D8D8D,thickness=2].> Discord : <color:#8D8D8D>posts leaderboards, strikes, DMs
BotTasks .[#8D8D8D,thickness=2].> MainDb : <color:#8D8D8D>reads / writes state
BotTasks .[#8D8D8D,thickness=2].> JsonFiles : <color:#8D8D8D>writes per-page JSON
@enduml
`;case`website`:return`@startuml
title "Website data flow — bot → JSON → Flask → tunnel → edge → browser"
left to right direction

hide stereotype
skinparam ranksep 60
skinparam nodesep 30
skinparam {
  arrowFontSize 10
  defaultTextAlignment center
  wrapWidth 200
  maxMessageSize 100
  shadowing false
}

skinparam rectangle<<Supervisor>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam person<<Viewer>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam rectangle<<BotTasks>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam rectangle<<Tunnel>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam rectangle<<Flask>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam database<<JsonFiles>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam rectangle<<EdgeHub>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam rectangle<<EdgeLogsite>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
rectangle "Wave Management Bot" <<Bot>> as Bot {
  skinparam RectangleBorderColor<<Bot>> #3b82f6
  skinparam RectangleFontColor<<Bot>> #3b82f6
  skinparam RectangleBorderStyle<<Bot>> dashed

  rectangle "==tasks/ background loops\\n\\nScheduled jobs & queues" <<BotTasks>> as BotTasks
}
rectangle "==staff_hub_serve.py\\n\\nSupervisor" <<Supervisor>> as Supervisor
person "==Hub viewer\\n\\nStaff member viewing the leaderboards in a browser" <<Viewer>> as Viewer
rectangle "Cloudflare Pages" <<Edge>> as Edge {
  skinparam RectangleBorderColor<<Edge>> #3b82f6
  skinparam RectangleFontColor<<Edge>> #3b82f6
  skinparam RectangleBorderStyle<<Edge>> dashed

  rectangle "==wavedropmaps.pages.dev\\n\\nWave Staff Hub — 9 leaderboard pages" <<EdgeHub>> as EdgeHub
  rectangle "==wave-logging.pages.dev\\n\\nWave-Logging dashboard" <<EdgeLogsite>> as EdgeLogsite
}
rectangle "==cloudflared tunnel\\n\\nQuick tunnel" <<Tunnel>> as Tunnel
rectangle "==web_api.py\\n\\nFlask origin @ 127.0.0.1:5000" <<Flask>> as Flask
database "==website/data/*.json\\n\\nBot-built payloads" <<JsonFiles>> as JsonFiles

BotTasks .[#8D8D8D,thickness=2].> JsonFiles : <color:#8D8D8D>writes per-page JSON
Flask .[#8D8D8D,thickness=2].> JsonFiles : <color:#8D8D8D>serves at /api/<key>
Supervisor .[#8D8D8D,thickness=2].> Flask : <color:#8D8D8D>runs & restarts
Supervisor .[#8D8D8D,thickness=2].> Tunnel : <color:#8D8D8D>runs & rewrites URL
Tunnel .[#8D8D8D,thickness=2].> Flask : <color:#8D8D8D>proxies :5000
Viewer .[#8D8D8D,thickness=2].> Edge : <color:#8D8D8D>opens hub in browser
Supervisor .[#8D8D8D,thickness=2].> Edge : <color:#8D8D8D>wrangler deploys workers
Edge .[#8D8D8D,thickness=2].> Tunnel : <color:#8D8D8D>proxies with X-API-Key
@enduml
`;case`crossbot`:return`@startuml
title "surge bridge"
left to right direction

hide stereotype
skinparam ranksep 60
skinparam nodesep 30
skinparam {
  arrowFontSize 10
  defaultTextAlignment center
  wrapWidth 200
  maxMessageSize 100
  shadowing false
}

skinparam person<<Staff>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam rectangle<<Logistics>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam rectangle<<Discord>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam database<<MainDb>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam rectangle<<BotMain>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
skinparam queue<<DmQueueDb>>{
  BackgroundColor #3b82f6
  FontColor #eff6ff
  BorderColor #2563eb
}
person "==Staff member\\n\\nDrop-map staff across the 3 guilds — earn points, get strikes & rewards" <<Staff>> as Staff
rectangle "==Wave Logistics Bot\\n\\nSibling bot on the same machine" <<Logistics>> as Logistics
rectangle "==Discord\\n\\ndiscord.py gateway across 3 guilds" <<Discord>> as Discord
database "==bot_database.db\\n<size:10>[SQLite · WAL · async pool]</size>\\n\\nSingle source of truth" <<MainDb>> as MainDb
rectangle "Wave Management Bot" <<Bot>> as Bot {
  skinparam RectangleBorderColor<<Bot>> #3b82f6
  skinparam RectangleFontColor<<Bot>> #3b82f6
  skinparam RectangleBorderStyle<<Bot>> dashed

  rectangle "==main.py\\n\\nEntry point" <<BotMain>> as BotMain
}
queue "==dm_shared_queue.db\\n<size:10>[SQLite on C:/Desktop]</size>\\n\\nCross-bot DM queue" <<DmQueueDb>> as DmQueueDb

Staff .[#8D8D8D,thickness=2].> Discord : <color:#8D8D8D>runs > commands
Discord .[#8D8D8D,thickness=2].> BotMain : <color:#8D8D8D>gateway events
BotMain .[#8D8D8D,thickness=2].> DmQueueDb : <color:#8D8D8D>enqueues every user.send()
Logistics .[#8D8D8D,thickness=2].> DmQueueDb : <color:#8D8D8D>shares the queue
DmQueueDb .[#8D8D8D,thickness=2].> BotMain : <color:#8D8D8D>worker claims & delivers
Logistics .[#8D8D8D,thickness=2].> MainDb : <color:#8D8D8D>feeds loot/surge queue codes
@enduml
`;default:throw Error(`Unknown viewId: `+e)}};export{e as pumlSource};