var e=e=>{switch(e){case`index`:return`---
title: "Wave Management Bot — whole-system landscape"
---
graph LR
  Staff@{ icon: "fa:user", shape: rounded, label: "Staff member" }
  Viewer@{ icon: "fa:user", shape: rounded, label: "Hub viewer" }
  Logistics@{ shape: rectangle, label: "Wave Logistics Bot" }
  Supervisor@{ shape: rectangle, label: "staff_hub_serve.py" }
  Discord@{ shape: rectangle, label: "Discord" }
  Edge@{ shape: rounded, label: "Cloudflare Pages" }
  Bot@{ shape: rectangle, label: "Wave Management Bot" }
  Tunnel@{ shape: rectangle, label: "cloudflared tunnel" }
  MainDb@{ shape: cylinder, label: "bot_database.db" }
  DmQueueDb@{ shape: horizontal-cylinder, label: "dm_shared_queue.db" }
  Trackers@{ shape: rectangle, label: "command-trackers/" }
  Flask@{ shape: rectangle, label: "web_api.py" }
  JsonFiles@{ shape: disk, label: "website/data/*.json" }
  Staff -. "\`runs > commands\`" .-> Discord
  Viewer -. "\`opens hub in browser\`" .-> Edge
  Discord -. "\`gateway events\`" .-> Bot
  Bot -. "\`[...]\`" .-> Discord
  Bot -. "\`reads / writes state\`" .-> MainDb
  Bot -. "\`enqueues every user.send()\`" .-> DmQueueDb
  Bot -. "\`shells out to scripts\`" .-> Trackers
  Bot -. "\`writes per-page JSON\`" .-> JsonFiles
  DmQueueDb -. "\`worker claims & delivers\`" .-> Bot
  Logistics -. "\`feeds loot/surge queue codes\`" .-> MainDb
  Logistics -. "\`shares the queue\`" .-> DmQueueDb
  Flask -. "\`serves at /api/<key>\`" .-> JsonFiles
  Supervisor -. "\`runs & restarts\`" .-> Flask
  Tunnel -. "\`proxies :5000\`" .-> Flask
  Supervisor -. "\`runs & rewrites URL\`" .-> Tunnel
  Supervisor -. "\`wrangler deploys workers\`" .-> Edge
  Edge -. "\`proxies with X-API-Key\`" .-> Tunnel
`;case`view_na89us`:return`---
title: "Inside the bot — main, cogs, tasks, core"
---
graph TB
  Discord@{ shape: rectangle, label: "Discord" }
  DmQueueDb@{ shape: horizontal-cylinder, label: "dm_shared_queue.db" }
  subgraph Bot["\`Wave Management Bot\`"]
    Bot.Main@{ shape: rectangle, label: "main.py" }
    Bot.Cogs@{ shape: rectangle, label: "commands/ cogs" }
    Bot.Tasks@{ shape: rectangle, label: "tasks/ background loops" }
    Bot.Core@{ shape: rectangle, label: "core/ helpers" }
  end
  Trackers@{ shape: rectangle, label: "command-trackers/" }
  MainDb@{ shape: cylinder, label: "bot_database.db" }
  JsonFiles@{ shape: disk, label: "website/data/*.json" }
  Discord -. "\`gateway events\`" .-> Bot.Main
  DmQueueDb -. "\`worker claims & delivers\`" .-> Bot.Main
  Bot.Main -. "\`loads & dispatches\`" .-> Bot.Cogs
  Bot.Main -. "\`starts loops\`" .-> Bot.Tasks
  Bot.Cogs -. "\`uses helpers\`" .-> Bot.Core
  Bot.Tasks -. "\`uses helpers\`" .-> Bot.Core
  Bot.Main -. "\`enqueues every user.send()\`" .-> DmQueueDb
  Bot.Cogs -. "\`replies, roles, embeds\`" .-> Discord
  Bot.Cogs -. "\`reads / writes state\`" .-> MainDb
  Bot.Cogs -. "\`shells out to scripts\`" .-> Trackers
  Bot.Tasks -. "\`posts leaderboards, strikes, DMs\`" .-> Discord
  Bot.Tasks -. "\`reads / writes state\`" .-> MainDb
  Bot.Tasks -. "\`writes per-page JSON\`" .-> JsonFiles
`;case`website`:return`---
title: "Website data flow — bot → JSON → Flask → tunnel → edge → browser"
---
graph LR
  subgraph Bot["\`Wave Management Bot\`"]
    Bot.Tasks@{ shape: rectangle, label: "tasks/ background loops" }
  end
  Supervisor@{ shape: rectangle, label: "staff_hub_serve.py" }
  Viewer@{ icon: "fa:user", shape: rounded, label: "Hub viewer" }
  subgraph Edge["\`Cloudflare Pages\`"]
    Edge.Hub@{ shape: rounded, label: "wavedropmaps.pages.dev" }
    Edge.Logsite@{ shape: rounded, label: "wave-logging.pages.dev" }
  end
  Tunnel@{ shape: rectangle, label: "cloudflared tunnel" }
  Flask@{ shape: rectangle, label: "web_api.py" }
  JsonFiles@{ shape: disk, label: "website/data/*.json" }
  Bot.Tasks -. "\`writes per-page JSON\`" .-> JsonFiles
  Flask -. "\`serves at /api/<key>\`" .-> JsonFiles
  Supervisor -. "\`runs & restarts\`" .-> Flask
  Supervisor -. "\`runs & rewrites URL\`" .-> Tunnel
  Tunnel -. "\`proxies :5000\`" .-> Flask
  Viewer -. "\`opens hub in browser\`" .-> Edge
  Supervisor -. "\`wrangler deploys workers\`" .-> Edge
  Edge -. "\`proxies with X-API-Key\`" .-> Tunnel
`;case`crossbot`:return`---
title: "surge bridge"
---
graph LR
  Staff@{ icon: "fa:user", shape: rounded, label: "Staff member" }
  Logistics@{ shape: rectangle, label: "Wave Logistics Bot" }
  Discord@{ shape: rectangle, label: "Discord" }
  MainDb@{ shape: cylinder, label: "bot_database.db" }
  subgraph Bot["\`Wave Management Bot\`"]
    Bot.Main@{ shape: rectangle, label: "main.py" }
  end
  DmQueueDb@{ shape: horizontal-cylinder, label: "dm_shared_queue.db" }
  Staff -. "\`runs > commands\`" .-> Discord
  Discord -. "\`gateway events\`" .-> Bot.Main
  Bot.Main -. "\`enqueues every user.send()\`" .-> DmQueueDb
  Logistics -. "\`shares the queue\`" .-> DmQueueDb
  DmQueueDb -. "\`worker claims & delivers\`" .-> Bot.Main
  Logistics -. "\`feeds loot/surge queue codes\`" .-> MainDb
`;default:throw Error(`Unknown viewId: `+e)}};export{e as mmdSource};