var e=e=>{switch(e){case`index`:return`direction: right

Staff: {
  label: "Staff member"
  shape: c4-person
}
Viewer: {
  label: "Hub viewer"
  shape: c4-person
}
Logistics: {
  label: "Wave Logistics Bot"
}
Supervisor: {
  label: "staff_hub_serve.py"
}
Discord: {
  label: "Discord"
}
Edge: {
  label: "Cloudflare Pages"
}
Bot: {
  label: "Wave Management Bot"
}
Tunnel: {
  label: "cloudflared tunnel"
}
MainDb: {
  label: "bot_database.db"
  shape: cylinder
}
DmQueueDb: {
  label: "dm_shared_queue.db"
  shape: queue
}
Trackers: {
  label: "command-trackers/"
}
Flask: {
  label: "web_api.py"
}
JsonFiles: {
  label: "website/data/*.json"
  shape: stored_data
}

Staff -> Discord: "runs > commands"
Viewer -> Edge: "opens hub in browser"
Discord -> Bot: "gateway events"
Bot -> Discord: "[...]"
Bot -> MainDb: "reads / writes state"
Bot -> DmQueueDb: "enqueues every user.send()"
Bot -> Trackers: "shells out to scripts"
Bot -> JsonFiles: "writes per-page JSON"
DmQueueDb -> Bot: "worker claims & delivers"
Logistics -> MainDb: "feeds loot/surge queue codes"
Logistics -> DmQueueDb: "shares the queue"
Flask -> JsonFiles: "serves at /api/<key>"
Supervisor -> Flask: "runs & restarts"
Tunnel -> Flask: "proxies :5000"
Supervisor -> Tunnel: "runs & rewrites URL"
Supervisor -> Edge: "wrangler deploys workers"
Edge -> Tunnel: "proxies with X-API-Key"
`;case`view_na89us`:return`direction: down

Discord: {
  label: "Discord"
}
DmQueueDb: {
  label: "dm_shared_queue.db"
  shape: queue
}
Bot: {
  label: "Wave Management Bot"

  Main: {
    label: "main.py"
  }
  Cogs: {
    label: "commands/ cogs"
  }
  Tasks: {
    label: "tasks/ background loops"
  }
  Core: {
    label: "core/ helpers"
  }
}
Trackers: {
  label: "command-trackers/"
}
MainDb: {
  label: "bot_database.db"
  shape: cylinder
}
JsonFiles: {
  label: "website/data/*.json"
  shape: stored_data
}

Discord -> Bot.Main: "gateway events"
DmQueueDb -> Bot.Main: "worker claims & delivers"
Bot.Main -> Bot.Cogs: "loads & dispatches"
Bot.Main -> Bot.Tasks: "starts loops"
Bot.Cogs -> Bot.Core: "uses helpers"
Bot.Tasks -> Bot.Core: "uses helpers"
Bot.Main -> DmQueueDb: "enqueues every user.send()"
Bot.Cogs -> Discord: "replies, roles, embeds"
Bot.Cogs -> MainDb: "reads / writes state"
Bot.Cogs -> Trackers: "shells out to scripts"
Bot.Tasks -> Discord: "posts leaderboards, strikes, DMs"
Bot.Tasks -> MainDb: "reads / writes state"
Bot.Tasks -> JsonFiles: "writes per-page JSON"
`;case`website`:return`direction: right

Bot: {
  label: "Wave Management Bot"

  Tasks: {
    label: "tasks/ background loops"
  }
}
Supervisor: {
  label: "staff_hub_serve.py"
}
Viewer: {
  label: "Hub viewer"
  shape: c4-person
}
Edge: {
  label: "Cloudflare Pages"

  Hub: {
    label: "wavedropmaps.pages.dev"
  }
  Logsite: {
    label: "wave-logging.pages.dev"
  }
}
Tunnel: {
  label: "cloudflared tunnel"
}
Flask: {
  label: "web_api.py"
}
JsonFiles: {
  label: "website/data/*.json"
  shape: stored_data
}

Bot.Tasks -> JsonFiles: "writes per-page JSON"
Flask -> JsonFiles: "serves at /api/<key>"
Supervisor -> Flask: "runs & restarts"
Supervisor -> Tunnel: "runs & rewrites URL"
Tunnel -> Flask: "proxies :5000"
Viewer -> Edge: "opens hub in browser"
Supervisor -> Edge: "wrangler deploys workers"
Edge -> Tunnel: "proxies with X-API-Key"
`;case`crossbot`:return`direction: right

Staff: {
  label: "Staff member"
  shape: c4-person
}
Logistics: {
  label: "Wave Logistics Bot"
}
Discord: {
  label: "Discord"
}
MainDb: {
  label: "bot_database.db"
  shape: cylinder
}
Bot: {
  label: "Wave Management Bot"

  Main: {
    label: "main.py"
  }
}
DmQueueDb: {
  label: "dm_shared_queue.db"
  shape: queue
}

Staff -> Discord: "runs > commands"
Discord -> Bot.Main: "gateway events"
Bot.Main -> DmQueueDb: "enqueues every user.send()"
Logistics -> DmQueueDb: "shares the queue"
DmQueueDb -> Bot.Main: "worker claims & delivers"
Logistics -> MainDb: "feeds loot/surge queue codes"
`;default:throw Error(`Unknown viewId: `+e)}};export{e as d2Source};