var e=e=>{switch(e){case`index`:return`digraph {
    graph [TBbalance=min,
        bgcolor=transparent,
        compound=true,
        fontname=Arial,
        fontsize=20,
        labeljust=l,
        labelloc=t,
        layout=dot,
        likec4_viewId=index,
        nodesep=1.528,
        outputorder=nodesfirst,
        pad=0.209,
        rankdir=LR,
        ranksep=1.667,
        splines=spline
    ];
    node [color="#2563eb",
        fillcolor="#3b82f6",
        fontcolor="#eff6ff",
        fontname=Arial,
        label="\\N",
        penwidth=0,
        shape=rect,
        style=filled
    ];
    edge [arrowsize=0.75,
        color="#8D8D8D",
        fontcolor="#C9C9C9",
        fontname=Arial,
        fontsize=14,
        penwidth=2,
        style=""
    ];
    staff [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">Staff member</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Drop-map staff across the 3 guilds — earn<BR/>points, get strikes &amp; rewards</FONT></TD></TR></TABLE>>,
        likec4_id=staff,
        likec4_level=0,
        margin="0.223,0.223",
        width=4.445];
    discord [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">Discord</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">discord.py gateway across 3 guilds</FONT></TD></TR></TABLE>>,
        likec4_id=discord,
        likec4_level=0,
        margin="0.223,0.223",
        width=4.445];
    staff -> discord [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">runs &gt; commands</FONT></TD></TR></TABLE>>,
        likec4_id=rwkq6g,
        minlen=1,
        style=dashed];
    viewer [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">Hub viewer</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Staff member viewing the leaderboards in a<BR/>browser</FONT></TD></TR></TABLE>>,
        likec4_id=viewer,
        likec4_level=0,
        margin="0.223,0.223",
        width=4.445];
    "edge" [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">Cloudflare Pages</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Edge gate (two sites)</FONT></TD></TR></TABLE>>,
        likec4_id="edge",
        likec4_level=0,
        margin="0.278,0.306",
        width=4.445];
    viewer -> "edge" [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">opens hub in browser</FONT></TD></TR></TABLE>>,
        likec4_id="1uq4e37",
        minlen=1,
        style=dashed];
    logistics [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">Wave Logistics Bot</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Sibling bot on the same machine</FONT></TD></TR></TABLE>>,
        likec4_id=logistics,
        likec4_level=0,
        margin="0.223,0.223",
        width=4.445];
    maindb [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">bot_database.db</FONT></TD></TR><TR><TD><FONT POINT-SIZE="13" COLOR="#bfdbfe">SQLite · WAL · async pool</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Single source of truth</FONT></TD></TR></TABLE>>,
        likec4_id=mainDb,
        likec4_level=0,
        margin="0.223,0",
        penwidth=2,
        shape=cylinder,
        width=4.445];
    logistics -> maindb [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">feeds loot/surge queue codes</FONT></TD></TR></TABLE>>,
        likec4_id=w2jm6s,
        style=dashed];
    dmqueuedb [height=2.389,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">dm_shared_queue.db</FONT></TD></TR><TR><TD><FONT POINT-SIZE="13" COLOR="#bfdbfe">SQLite on C:/Desktop</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Cross-bot DM queue</FONT></TD></TR></TABLE>>,
        likec4_id=dmQueueDb,
        likec4_level=0,
        margin="0.278,0.223",
        width=4.445];
    logistics -> dmqueuedb [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">shares the queue</FONT></TD></TR></TABLE>>,
        likec4_id="1oe93if",
        style=dashed];
    supervisor [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">staff_hub_serve.py</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Supervisor</FONT></TD></TR></TABLE>>,
        likec4_id=supervisor,
        likec4_level=0,
        margin="0.223,0.223",
        width=4.445];
    supervisor -> "edge" [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">wrangler deploys workers</FONT></TD></TR></TABLE>>,
        likec4_id="8t6dvd",
        style=dashed];
    tunnel [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">cloudflared tunnel</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Quick tunnel</FONT></TD></TR></TABLE>>,
        likec4_id=tunnel,
        likec4_level=0,
        margin="0.223,0.223",
        width=4.445];
    supervisor -> tunnel [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">runs &amp; rewrites URL</FONT></TD></TR></TABLE>>,
        likec4_id="1v0n0b6",
        style=dashed];
    flask [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">web_api.py</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Flask origin @ 127.0.0.1:5000</FONT></TD></TR></TABLE>>,
        likec4_id=flask,
        likec4_level=0,
        margin="0.223,0.223",
        width=4.445];
    supervisor -> flask [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">runs &amp; restarts</FONT></TD></TR></TABLE>>,
        likec4_id="6iqq7d",
        style=dashed];
    bot [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">Wave Management Bot</FONT></TD></TR><TR><TD><FONT POINT-SIZE="13" COLOR="#bfdbfe">Python / discord.py</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">The Discord staff-management bot</FONT></TD></TR></TABLE>>,
        likec4_id=bot,
        likec4_level=0,
        margin="0.223,0.223",
        width=4.445];
    discord -> bot [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">gateway events</FONT></TD></TR></TABLE>>,
        likec4_id="12tmi5z",
        style=dashed];
    "edge" -> tunnel [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">proxies with X-API-Key</FONT></TD></TR></TABLE>>,
        likec4_id=zbxidd,
        style=dashed];
    bot -> discord [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14"><B>[...]</B></FONT></TD></TR></TABLE>>,
        likec4_id="1z02wl3",
        style=dashed];
    bot -> maindb [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">reads / writes state</FONT></TD></TR></TABLE>>,
        likec4_id=hsngri,
        style=dashed];
    bot -> dmqueuedb [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">enqueues every user.send()</FONT></TD></TR></TABLE>>,
        likec4_id="1mj45l9",
        style=dashed];
    trackers [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">command-trackers/</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Data trackers shelled out to</FONT></TD></TR></TABLE>>,
        likec4_id=trackers,
        likec4_level=0,
        margin="0.223,0.223",
        width=4.445];
    bot -> trackers [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">shells out to scripts</FONT></TD></TR></TABLE>>,
        likec4_id="3vnbqw",
        minlen=1,
        style=dashed];
    jsonfiles [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">website/data/*.json</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Bot-built payloads</FONT></TD></TR></TABLE>>,
        likec4_id=jsonFiles,
        likec4_level=0,
        margin="0.223,0",
        penwidth=2,
        shape=cylinder,
        width=4.445];
    bot -> jsonfiles [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">writes per-page JSON</FONT></TD></TR></TABLE>>,
        likec4_id=sitny6,
        style=dashed];
    tunnel -> flask [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">proxies :5000</FONT></TD></TR></TABLE>>,
        likec4_id=xasw8h,
        style=dashed];
    dmqueuedb -> bot [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">worker claims &amp; delivers</FONT></TD></TR></TABLE>>,
        likec4_id="5wjiz1",
        style=dashed];
    flask -> jsonfiles [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">serves at /api/&lt;key&gt;</FONT></TD></TR></TABLE>>,
        likec4_id="1p0pxkk",
        style=dashed];
}
`;case`view_na89us`:return`digraph {
    graph [TBbalance=min,
        bgcolor=transparent,
        compound=true,
        fontname=Arial,
        fontsize=20,
        labeljust=l,
        labelloc=t,
        layout=dot,
        likec4_viewId=view_na89us,
        nodesep=1.528,
        outputorder=nodesfirst,
        pad=0.209,
        rankdir=TB,
        ranksep=1.667,
        splines=spline
    ];
    node [color="#2563eb",
        fillcolor="#3b82f6",
        fontcolor="#eff6ff",
        fontname=Arial,
        label="\\N",
        penwidth=0,
        shape=rect,
        style=filled
    ];
    edge [arrowsize=0.75,
        color="#8D8D8D",
        fontcolor="#C9C9C9",
        fontname=Arial,
        fontsize=14,
        penwidth=2,
        style=""
    ];
    subgraph cluster_bot {
        graph [color="#1b3d88",
            fillcolor="#194b9e",
            label=<<FONT POINT-SIZE="11" COLOR="#bfdbfeb3"><B>WAVE MANAGEMENT BOT</B></FONT>>,
            likec4_depth=1,
            likec4_id=bot,
            likec4_level=0,
            margin=40,
            style=filled
        ];
        main [group=bot,
            height=2.5,
            label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">main.py</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Entry point</FONT></TD></TR></TABLE>>,
            likec4_id="bot.main",
            likec4_level=1,
            margin="0.223,0.223",
            width=4.445];
        cogs [group=bot,
            height=2.5,
            label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">commands/ cogs</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Game &amp; admin systems</FONT></TD></TR></TABLE>>,
            likec4_id="bot.cogs",
            likec4_level=1,
            margin="0.223,0.223",
            width=4.445];
        tasks [group=bot,
            height=2.5,
            label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">tasks/ background loops</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Scheduled jobs &amp; queues</FONT></TD></TR></TABLE>>,
            likec4_id="bot.tasks",
            likec4_level=1,
            margin="0.223,0.223",
            width=4.445];
        core [group=bot,
            height=2.5,
            label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">core/ helpers</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Shared helpers &amp; config</FONT></TD></TR></TABLE>>,
            likec4_id="bot.core",
            likec4_level=1,
            margin="0.223,0.223",
            width=4.445];
    }
    discord [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">Discord</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">discord.py gateway across 3 guilds</FONT></TD></TR></TABLE>>,
        likec4_id=discord,
        likec4_level=0,
        margin="0.223,0.223",
        width=4.445];
    discord -> main [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">gateway events</FONT></TD></TR></TABLE>>,
        likec4_id="2m0awi",
        style=dashed];
    dmqueuedb [height=2.389,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">dm_shared_queue.db</FONT></TD></TR><TR><TD><FONT POINT-SIZE="13" COLOR="#bfdbfe">SQLite on C:/Desktop</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Cross-bot DM queue</FONT></TD></TR></TABLE>>,
        likec4_id=dmQueueDb,
        likec4_level=0,
        margin="0.278,0.223",
        width=4.445];
    dmqueuedb -> main [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">worker claims &amp; delivers</FONT></TD></TR></TABLE>>,
        likec4_id="18fzvgo",
        style=dashed];
    main -> dmqueuedb [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">enqueues every user.send()</FONT></TD></TR></TABLE>>,
        likec4_id="1iev8p4",
        style=dashed];
    main -> cogs [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">loads &amp; dispatches</FONT></TD></TR></TABLE>>,
        likec4_id="1fojmmx",
        style=dashed,
        weight=2];
    main -> tasks [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">starts loops</FONT></TD></TR></TABLE>>,
        likec4_id="10bysf",
        style=dashed,
        weight=2];
    cogs -> discord [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">replies, roles, embeds</FONT></TD></TR></TABLE>>,
        likec4_id=g3a129,
        style=dashed];
    trackers [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">command-trackers/</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Data trackers shelled out to</FONT></TD></TR></TABLE>>,
        likec4_id=trackers,
        likec4_level=0,
        margin="0.223,0.223",
        width=4.445];
    cogs -> trackers [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">shells out to scripts</FONT></TD></TR></TABLE>>,
        likec4_id=nb9bhq,
        minlen=1,
        style=dashed];
    cogs -> core [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">uses helpers</FONT></TD></TR></TABLE>>,
        likec4_id="127dudl",
        style=dashed,
        weight=2];
    maindb [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">bot_database.db</FONT></TD></TR><TR><TD><FONT POINT-SIZE="13" COLOR="#bfdbfe">SQLite · WAL · async pool</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Single source of truth</FONT></TD></TR></TABLE>>,
        likec4_id=mainDb,
        likec4_level=0,
        margin="0.223,0",
        penwidth=2,
        shape=cylinder,
        width=4.445];
    cogs -> maindb [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">reads / writes state</FONT></TD></TR></TABLE>>,
        likec4_id="1075qko",
        style=dashed];
    tasks -> discord [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">posts leaderboards, strikes, DMs</FONT></TD></TR></TABLE>>,
        likec4_id="1oj37tz",
        style=dashed];
    tasks -> core [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">uses helpers</FONT></TD></TR></TABLE>>,
        likec4_id="1ghqrin",
        style=dashed,
        weight=2];
    tasks -> maindb [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">reads / writes state</FONT></TD></TR></TABLE>>,
        likec4_id="1sta9am",
        style=dashed];
    jsonfiles [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">website/data/*.json</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Bot-built payloads</FONT></TD></TR></TABLE>>,
        likec4_id=jsonFiles,
        likec4_level=0,
        margin="0.223,0",
        penwidth=2,
        shape=cylinder,
        width=4.445];
    tasks -> jsonfiles [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">writes per-page JSON</FONT></TD></TR></TABLE>>,
        likec4_id="1i4ugry",
        minlen=1,
        style=dashed];
}
`;case`website`:return`digraph {
    graph [TBbalance=min,
        bgcolor=transparent,
        compound=true,
        fontname=Arial,
        fontsize=20,
        labeljust=l,
        labelloc=t,
        layout=dot,
        likec4_viewId=website,
        nodesep=1.528,
        outputorder=nodesfirst,
        pad=0.209,
        rankdir=LR,
        ranksep=1.667,
        splines=spline
    ];
    node [color="#2563eb",
        fillcolor="#3b82f6",
        fontcolor="#eff6ff",
        fontname=Arial,
        label="\\N",
        penwidth=0,
        shape=rect,
        style=filled
    ];
    edge [arrowsize=0.75,
        color="#8D8D8D",
        fontcolor="#C9C9C9",
        fontname=Arial,
        fontsize=14,
        penwidth=2,
        style=""
    ];
    subgraph cluster_bot {
        graph [color="#1b3d88",
            fillcolor="#194b9e",
            label=<<FONT POINT-SIZE="11" COLOR="#bfdbfeb3"><B>WAVE MANAGEMENT BOT</B></FONT>>,
            likec4_depth=1,
            likec4_id=bot,
            likec4_level=0,
            margin=32,
            style=filled
        ];
        tasks [height=2.5,
            label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">tasks/ background loops</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Scheduled jobs &amp; queues</FONT></TD></TR></TABLE>>,
            likec4_id="bot.tasks",
            likec4_level=1,
            margin="0.223,0.223",
            width=4.445];
    }
    subgraph cluster_edge {
        graph [color="#1b3d88",
            fillcolor="#194b9e",
            label=<<FONT POINT-SIZE="11" COLOR="#bfdbfeb3"><B>CLOUDFLARE PAGES</B></FONT>>,
            likec4_depth=1,
            likec4_id="edge",
            likec4_level=0,
            margin=40,
            style=filled
        ];
        hub [height=2.5,
            label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">wavedropmaps.pages.dev</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Wave Staff Hub — 9 leaderboard pages</FONT></TD></TR></TABLE>>,
            likec4_id="edge.hub",
            likec4_level=1,
            margin="0.278,0.306",
            width=4.445];
        logsite [height=2.5,
            label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">wave-logging.pages.dev</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Wave-Logging dashboard</FONT></TD></TR></TABLE>>,
            likec4_id="edge.logsite",
            likec4_level=1,
            margin="0.278,0.306",
            width=4.445];
    }
    supervisor [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">staff_hub_serve.py</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Supervisor</FONT></TD></TR></TABLE>>,
        likec4_id=supervisor,
        likec4_level=0,
        margin="0.223,0.223",
        width=4.445];
    tunnel [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">cloudflared tunnel</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Quick tunnel</FONT></TD></TR></TABLE>>,
        likec4_id=tunnel,
        likec4_level=0,
        margin="0.223,0.223",
        width=4.445];
    supervisor -> tunnel [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">runs &amp; rewrites URL</FONT></TD></TR></TABLE>>,
        likec4_id="1v0n0b6",
        style=dashed];
    flask [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">web_api.py</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Flask origin @ 127.0.0.1:5000</FONT></TD></TR></TABLE>>,
        likec4_id=flask,
        likec4_level=0,
        margin="0.223,0.223",
        width=4.445];
    supervisor -> flask [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">runs &amp; restarts</FONT></TD></TR></TABLE>>,
        likec4_id="6iqq7d",
        style=dashed];
    supervisor -> hub [arrowhead=normal,
        lhead=cluster_edge,
        likec4_id="8t6dvd",
        style=dashed,
        xlabel=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">wrangler deploys workers</FONT></TD></TR></TABLE>>];
    viewer [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">Hub viewer</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Staff member viewing the leaderboards in a<BR/>browser</FONT></TD></TR></TABLE>>,
        likec4_id=viewer,
        likec4_level=0,
        margin="0.223,0.223",
        width=4.445];
    viewer -> hub [arrowhead=normal,
        lhead=cluster_edge,
        likec4_id="1uq4e37",
        minlen=1,
        style=dashed,
        xlabel=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">opens hub in browser</FONT></TD></TR></TABLE>>];
    jsonfiles [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">website/data/*.json</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Bot-built payloads</FONT></TD></TR></TABLE>>,
        likec4_id=jsonFiles,
        likec4_level=0,
        margin="0.223,0",
        penwidth=2,
        shape=cylinder,
        width=4.445];
    tasks -> jsonfiles [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">writes per-page JSON</FONT></TD></TR></TABLE>>,
        likec4_id="1i4ugry",
        minlen=1,
        style=dashed];
    tunnel -> flask [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">proxies :5000</FONT></TD></TR></TABLE>>,
        likec4_id=xasw8h,
        style=dashed];
    flask -> jsonfiles [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">serves at /api/&lt;key&gt;</FONT></TD></TR></TABLE>>,
        likec4_id="1p0pxkk",
        style=dashed,
        weight=2];
    logsite -> tunnel [arrowhead=normal,
        likec4_id=zbxidd,
        ltail=cluster_edge,
        minlen=1,
        style=dashed,
        xlabel=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">proxies with X-API-Key</FONT></TD></TR></TABLE>>];
}
`;case`crossbot`:return`digraph {
    graph [TBbalance=min,
        bgcolor=transparent,
        compound=true,
        fontname=Arial,
        fontsize=20,
        labeljust=l,
        labelloc=t,
        layout=dot,
        likec4_viewId=crossbot,
        nodesep=1.528,
        outputorder=nodesfirst,
        pad=0.209,
        rankdir=LR,
        ranksep=1.667,
        splines=spline
    ];
    node [color="#2563eb",
        fillcolor="#3b82f6",
        fontcolor="#eff6ff",
        fontname=Arial,
        label="\\N",
        penwidth=0,
        shape=rect,
        style=filled
    ];
    edge [arrowsize=0.75,
        color="#8D8D8D",
        fontcolor="#C9C9C9",
        fontname=Arial,
        fontsize=14,
        penwidth=2,
        style=""
    ];
    subgraph cluster_bot {
        graph [color="#1b3d88",
            fillcolor="#194b9e",
            label=<<FONT POINT-SIZE="11" COLOR="#bfdbfeb3"><B>WAVE MANAGEMENT BOT</B></FONT>>,
            likec4_depth=1,
            likec4_id=bot,
            likec4_level=0,
            margin=32,
            style=filled
        ];
        main [height=2.5,
            label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">main.py</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Entry point</FONT></TD></TR></TABLE>>,
            likec4_id="bot.main",
            likec4_level=1,
            margin="0.223,0.223",
            width=4.445];
    }
    staff [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">Staff member</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Drop-map staff across the 3 guilds — earn<BR/>points, get strikes &amp; rewards</FONT></TD></TR></TABLE>>,
        likec4_id=staff,
        likec4_level=0,
        margin="0.223,0.223",
        width=4.445];
    discord [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">Discord</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">discord.py gateway across 3 guilds</FONT></TD></TR></TABLE>>,
        likec4_id=discord,
        likec4_level=0,
        margin="0.223,0.223",
        width=4.445];
    staff -> discord [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">runs &gt; commands</FONT></TD></TR></TABLE>>,
        likec4_id=rwkq6g,
        minlen=1,
        style=dashed,
        weight=2];
    logistics [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">Wave Logistics Bot</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Sibling bot on the same machine</FONT></TD></TR></TABLE>>,
        likec4_id=logistics,
        likec4_level=0,
        margin="0.223,0.223",
        width=4.445];
    maindb [height=2.5,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">bot_database.db</FONT></TD></TR><TR><TD><FONT POINT-SIZE="13" COLOR="#bfdbfe">SQLite · WAL · async pool</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Single source of truth</FONT></TD></TR></TABLE>>,
        likec4_id=mainDb,
        likec4_level=0,
        margin="0.223,0",
        penwidth=2,
        shape=cylinder,
        width=4.445];
    logistics -> maindb [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">feeds loot/surge queue codes</FONT></TD></TR></TABLE>>,
        likec4_id=w2jm6s,
        minlen=1,
        style=dashed];
    dmqueuedb [height=2.389,
        label=<<TABLE BORDER="0" CELLPADDING="0" CELLSPACING="4"><TR><TD><FONT POINT-SIZE="20">dm_shared_queue.db</FONT></TD></TR><TR><TD><FONT POINT-SIZE="13" COLOR="#bfdbfe">SQLite on C:/Desktop</FONT></TD></TR><TR><TD><FONT POINT-SIZE="15" COLOR="#bfdbfe">Cross-bot DM queue</FONT></TD></TR></TABLE>>,
        likec4_id=dmQueueDb,
        likec4_level=0,
        margin="0.278,0.223",
        width=4.445];
    logistics -> dmqueuedb [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">shares the queue</FONT></TD></TR></TABLE>>,
        likec4_id="1oe93if",
        style=dashed,
        weight=2];
    discord -> main [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">gateway events</FONT></TD></TR></TABLE>>,
        likec4_id="2m0awi",
        style=dashed];
    main -> dmqueuedb [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">enqueues every user.send()</FONT></TD></TR></TABLE>>,
        likec4_id="1iev8p4",
        style=dashed];
    dmqueuedb -> main [arrowhead=normal,
        label=<<TABLE BORDER="0" CELLPADDING="3" CELLSPACING="0" BGCOLOR="#18191BA0"><TR><TD ALIGN="TEXT" BALIGN="LEFT"><FONT POINT-SIZE="14">worker claims &amp; delivers</FONT></TD></TR></TABLE>>,
        likec4_id="18fzvgo",
        style=dashed];
}
`;default:throw Error(`Unknown viewId: `+e)}},t=e=>{switch(e){case`index`:return`<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"
 "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
<!-- Generated by graphviz version 14.1.5 (0)
 -->
<!-- Pages: 1 -->
<svg width="2717pt" height="1553pt"
 viewBox="0.00 0.00 2717.00 1553.00" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
<g id="graph0" class="graph" transform="scale(1 1) rotate(0) translate(15.05 1537.85)">
<!-- staff -->
<g id="node1" class="node">
<title>staff</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="324.74,-982 4.7,-982 4.7,-802 324.74,-802 324.74,-982"/>
<text xml:space="preserve" text-anchor="start" x="104.7" y="-904" font-family="Arial" font-size="20.00" fill="#eff6ff">Staff member</text>
<text xml:space="preserve" text-anchor="start" x="25.07" y="-881" font-family="Arial" font-size="15.00" fill="#bfdbfe">Drop&#45;map staff across the 3 guilds — earn</text>
<text xml:space="preserve" text-anchor="start" x="70.51" y="-863" font-family="Arial" font-size="15.00" fill="#bfdbfe">points, get strikes &amp; rewards</text>
</g>
<!-- discord -->
<g id="node2" class="node">
<title>discord</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="1523.4,-982 1203.36,-982 1203.36,-802 1523.4,-802 1523.4,-982"/>
<text xml:space="preserve" text-anchor="start" x="1329.49" y="-895" font-family="Arial" font-size="20.00" fill="#eff6ff">Discord</text>
<text xml:space="preserve" text-anchor="start" x="1247.07" y="-872" font-family="Arial" font-size="15.00" fill="#bfdbfe">discord.py gateway across 3 guilds</text>
</g>
<!-- viewer -->
<g id="node3" class="node">
<title>viewer</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="329.43,-180 0,-180 0,0 329.43,0 329.43,-180"/>
<text xml:space="preserve" text-anchor="start" x="114.7" y="-102" font-family="Arial" font-size="20.00" fill="#eff6ff">Hub viewer</text>
<text xml:space="preserve" text-anchor="start" x="20.06" y="-79" font-family="Arial" font-size="15.00" fill="#bfdbfe">Staff member viewing the leaderboards in a</text>
<text xml:space="preserve" text-anchor="start" x="138.04" y="-61" font-family="Arial" font-size="15.00" fill="#bfdbfe">browser</text>
</g>
<!-- edge -->
<g id="node4" class="node">
<title>edge</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="934.2,-180 614.16,-180 614.16,0 934.2,0 934.2,-180"/>
<text xml:space="preserve" text-anchor="start" x="697.47" y="-93" font-family="Arial" font-size="20.00" fill="#eff6ff">Cloudflare Pages</text>
<text xml:space="preserve" text-anchor="start" x="703.73" y="-70" font-family="Arial" font-size="15.00" fill="#bfdbfe">Edge gate (two sites)</text>
</g>
<!-- logistics -->
<g id="node5" class="node">
<title>logistics</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="324.74,-1469 4.7,-1469 4.7,-1289 324.74,-1289 324.74,-1469"/>
<text xml:space="preserve" text-anchor="start" x="79.68" y="-1382" font-family="Arial" font-size="20.00" fill="#eff6ff">Wave Logistics Bot</text>
<text xml:space="preserve" text-anchor="start" x="55.9" y="-1359" font-family="Arial" font-size="15.00" fill="#bfdbfe">Sibling bot on the same machine</text>
</g>
<!-- maindb -->
<g id="node6" class="node">
<title>maindb</title>
<path fill="#3b82f6" stroke="#2563eb" stroke-width="2" d="M2687.09,-1488.64C2687.09,-1497.67 2615.36,-1505 2527.07,-1505 2438.77,-1505 2367.05,-1497.67 2367.05,-1488.64 2367.05,-1488.64 2367.05,-1341.36 2367.05,-1341.36 2367.05,-1332.33 2438.77,-1325 2527.07,-1325 2615.36,-1325 2687.09,-1332.33 2687.09,-1341.36 2687.09,-1341.36 2687.09,-1488.64 2687.09,-1488.64"/>
<path fill="none" stroke="#2563eb" stroke-width="2" d="M2687.09,-1488.64C2687.09,-1479.61 2615.36,-1472.27 2527.07,-1472.27 2438.77,-1472.27 2367.05,-1479.61 2367.05,-1488.64"/>
<text xml:space="preserve" text-anchor="start" x="2452.56" y="-1427.8" font-family="Arial" font-size="20.00" fill="#eff6ff">bot_database.db</text>
<text xml:space="preserve" text-anchor="start" x="2447.59" y="-1406.8" font-family="Arial" font-size="13.00" fill="#bfdbfe">SQLite · WAL · async pool</text>
<text xml:space="preserve" text-anchor="start" x="2456.19" y="-1385.2" font-family="Arial" font-size="15.00" fill="#bfdbfe">Single source of truth</text>
</g>
<!-- dmqueuedb -->
<g id="node7" class="node">
<title>dmqueuedb</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="2687.09,-848 2367.05,-848 2367.05,-676 2687.09,-676 2687.09,-848"/>
<text xml:space="preserve" text-anchor="start" x="2429.77" y="-774.8" font-family="Arial" font-size="20.00" fill="#eff6ff">dm_shared_queue.db</text>
<text xml:space="preserve" text-anchor="start" x="2464.2" y="-753.8" font-family="Arial" font-size="13.00" fill="#bfdbfe">SQLite on C:/Desktop</text>
<text xml:space="preserve" text-anchor="start" x="2457.87" y="-732.2" font-family="Arial" font-size="15.00" fill="#bfdbfe">Cross&#45;bot DM queue</text>
</g>
<!-- supervisor -->
<g id="node8" class="node">
<title>supervisor</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="324.74,-490 4.7,-490 4.7,-310 324.74,-310 324.74,-490"/>
<text xml:space="preserve" text-anchor="start" x="80.22" y="-403" font-family="Arial" font-size="20.00" fill="#eff6ff">staff_hub_serve.py</text>
<text xml:space="preserve" text-anchor="start" x="128.87" y="-380" font-family="Arial" font-size="15.00" fill="#bfdbfe">Supervisor</text>
</g>
<!-- tunnel -->
<g id="node9" class="node">
<title>tunnel</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="1523.4,-423 1203.36,-423 1203.36,-243 1523.4,-243 1523.4,-423"/>
<text xml:space="preserve" text-anchor="start" x="1284.44" y="-336" font-family="Arial" font-size="20.00" fill="#eff6ff">cloudflared tunnel</text>
<text xml:space="preserve" text-anchor="start" x="1321.69" y="-313" font-family="Arial" font-size="15.00" fill="#bfdbfe">Quick tunnel</text>
</g>
<!-- flask -->
<g id="node10" class="node">
<title>flask</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="2066.72,-566 1746.68,-566 1746.68,-386 2066.72,-386 2066.72,-566"/>
<text xml:space="preserve" text-anchor="start" x="1856.11" y="-479" font-family="Arial" font-size="20.00" fill="#eff6ff">web_api.py</text>
<text xml:space="preserve" text-anchor="start" x="1806.53" y="-456" font-family="Arial" font-size="15.00" fill="#bfdbfe">Flask origin @ 127.0.0.1:5000</text>
</g>
<!-- bot -->
<g id="node11" class="node">
<title>bot</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="2066.72,-987 1746.68,-987 1746.68,-807 2066.72,-807 2066.72,-987"/>
<text xml:space="preserve" text-anchor="start" x="1802.21" y="-909.8" font-family="Arial" font-size="20.00" fill="#eff6ff">Wave Management Bot</text>
<text xml:space="preserve" text-anchor="start" x="1851.43" y="-888.8" font-family="Arial" font-size="13.00" fill="#bfdbfe">Python / discord.py</text>
<text xml:space="preserve" text-anchor="start" x="1791.23" y="-867.2" font-family="Arial" font-size="15.00" fill="#bfdbfe">The Discord staff&#45;management bot</text>
</g>
<!-- trackers -->
<g id="node12" class="node">
<title>trackers</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="2687.09,-1138 2367.05,-1138 2367.05,-958 2687.09,-958 2687.09,-1138"/>
<text xml:space="preserve" text-anchor="start" x="2441.49" y="-1051" font-family="Arial" font-size="20.00" fill="#eff6ff">command&#45;trackers/</text>
<text xml:space="preserve" text-anchor="start" x="2435.77" y="-1028" font-family="Arial" font-size="15.00" fill="#bfdbfe">Data trackers shelled out to</text>
</g>
<!-- jsonfiles -->
<g id="node13" class="node">
<title>jsonfiles</title>
<path fill="#3b82f6" stroke="#2563eb" stroke-width="2" d="M2687.09,-549.64C2687.09,-558.67 2615.36,-566 2527.07,-566 2438.77,-566 2367.05,-558.67 2367.05,-549.64 2367.05,-549.64 2367.05,-402.36 2367.05,-402.36 2367.05,-393.33 2438.77,-386 2527.07,-386 2615.36,-386 2687.09,-393.33 2687.09,-402.36 2687.09,-402.36 2687.09,-549.64 2687.09,-549.64"/>
<path fill="none" stroke="#2563eb" stroke-width="2" d="M2687.09,-549.64C2687.09,-540.61 2615.36,-533.27 2527.07,-533.27 2438.77,-533.27 2367.05,-540.61 2367.05,-549.64"/>
<text xml:space="preserve" text-anchor="start" x="2443.13" y="-479" font-family="Arial" font-size="20.00" fill="#eff6ff">website/data/*.json</text>
<text xml:space="preserve" text-anchor="start" x="2467.45" y="-456" font-family="Arial" font-size="15.00" fill="#bfdbfe">Bot&#45;built payloads</text>
</g>
<!-- staff&#45;&gt;discord -->
<g id="edge1" class="edge">
<title>staff&#45;&gt;discord</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M324.62,-892C550.46,-892 962.45,-892 1193.58,-892"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="1193.24,-894.63 1200.74,-892 1193.24,-889.38 1193.24,-894.63"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="715.35,-892 715.35,-914.8 833.01,-914.8 833.01,-892 715.35,-892"/>
<text xml:space="preserve" text-anchor="start" x="718.35" y="-897.8" font-family="Arial" font-size="14.00" fill="#c9c9c9">runs &gt; commands</text>
</g>
<!-- discord&#45;&gt;bot -->
<g id="edge8" class="edge">
<title>discord&#45;&gt;bot</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M1523.14,-893.47C1590.2,-894.09 1668.39,-894.81 1736.54,-895.44"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="1736.4,-898.06 1743.92,-895.51 1736.45,-892.81 1736.4,-898.06"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="1583.4,-894.95 1583.4,-917.75 1686.68,-917.75 1686.68,-894.95 1583.4,-894.95"/>
<text xml:space="preserve" text-anchor="start" x="1586.4" y="-900.75" font-family="Arial" font-size="14.00" fill="#c9c9c9">gateway events</text>
</g>
<!-- viewer&#45;&gt;edge -->
<g id="edge2" class="edge">
<title>viewer&#45;&gt;edge</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M329.31,-90C414.32,-90 518.09,-90 603.92,-90"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="603.76,-92.63 611.26,-90 603.76,-87.38 603.76,-92.63"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="401.87,-90 401.87,-112.8 541.73,-112.8 541.73,-90 401.87,-90"/>
<text xml:space="preserve" text-anchor="start" x="404.87" y="-95.8" font-family="Arial" font-size="14.00" fill="#c9c9c9">opens hub in browser</text>
</g>
<!-- edge&#45;&gt;tunnel -->
<g id="edge9" class="edge">
<title>edge&#45;&gt;tunnel</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M934.09,-155.76C1014.62,-189.09 1112.42,-229.56 1194.22,-263.41"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="1192.87,-265.69 1200.81,-266.14 1194.88,-260.84 1192.87,-265.69"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="994.2,-240.41 994.2,-263.21 1143.36,-263.21 1143.36,-240.41 994.2,-240.41"/>
<text xml:space="preserve" text-anchor="start" x="997.2" y="-246.21" font-family="Arial" font-size="14.00" fill="#c9c9c9">proxies with X&#45;API&#45;Key</text>
</g>
<!-- logistics&#45;&gt;maindb -->
<g id="edge3" class="edge">
<title>logistics&#45;&gt;maindb</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M324.51,-1428.39C446.08,-1461.85 618.6,-1500 773.18,-1500 773.18,-1500 773.18,-1500 1907.7,-1500 2060.27,-1500 2232.06,-1474.29 2355.78,-1451.15"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="2356.24,-1453.73 2363.12,-1449.77 2355.27,-1448.58 2356.24,-1453.73"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="1268.54,-1500 1268.54,-1522.8 1458.23,-1522.8 1458.23,-1500 1268.54,-1500"/>
<text xml:space="preserve" text-anchor="start" x="1271.54" y="-1505.8" font-family="Arial" font-size="14.00" fill="#c9c9c9">feeds loot/surge queue codes</text>
</g>
<!-- logistics&#45;&gt;dmqueuedb -->
<g id="edge4" class="edge">
<title>logistics&#45;&gt;dmqueuedb</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M324.48,-1329.2C446.04,-1295.47 618.55,-1257 773.18,-1257 773.18,-1257 773.18,-1257 1907.7,-1257 2087.18,-1257 2176.87,-1320.56 2307.05,-1197 2403.78,-1105.19 2300.4,-1018.51 2367.05,-903 2376.95,-885.83 2389.7,-869.67 2403.66,-854.83"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="2405.17,-857.05 2408.5,-849.83 2401.4,-853.39 2405.17,-857.05"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="1306.29,-1257 1306.29,-1279.8 1420.48,-1279.8 1420.48,-1257 1306.29,-1257"/>
<text xml:space="preserve" text-anchor="start" x="1309.29" y="-1262.8" font-family="Arial" font-size="14.00" fill="#c9c9c9">shares the queue</text>
</g>
<!-- dmqueuedb&#45;&gt;bot -->
<g id="edge16" class="edge">
<title>dmqueuedb&#45;&gt;bot</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M2367.35,-743.02C2292.97,-739.02 2203.94,-741.35 2126.72,-763.2 2096.26,-771.82 2065.83,-785.96 2037.76,-801.9"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="2036.53,-799.58 2031.36,-805.61 2039.16,-804.12 2036.53,-799.58"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="2138.42,-763.2 2138.42,-786 2295.35,-786 2295.35,-763.2 2138.42,-763.2"/>
<text xml:space="preserve" text-anchor="start" x="2141.42" y="-769" font-family="Arial" font-size="14.00" fill="#c9c9c9">worker claims &amp; delivers</text>
</g>
<!-- supervisor&#45;&gt;edge -->
<g id="edge5" class="edge">
<title>supervisor&#45;&gt;edge</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M324.53,-318.96C410.77,-274.95 517.36,-220.55 605.01,-175.82"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="606.06,-178.23 611.55,-172.48 603.68,-173.56 606.06,-178.23"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="389.43,-281.88 389.43,-304.68 554.16,-304.68 554.16,-281.88 389.43,-281.88"/>
<text xml:space="preserve" text-anchor="start" x="392.43" y="-287.68" font-family="Arial" font-size="14.00" fill="#c9c9c9">wrangler deploys workers</text>
</g>
<!-- supervisor&#45;&gt;tunnel -->
<g id="edge6" class="edge">
<title>supervisor&#45;&gt;tunnel</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M324.62,-391.1C550.46,-378.46 962.45,-355.39 1193.58,-342.45"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="1193.41,-345.09 1200.75,-342.05 1193.11,-339.85 1193.41,-345.09"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="708.56,-374.25 708.56,-397.05 839.81,-397.05 839.81,-374.25 708.56,-374.25"/>
<text xml:space="preserve" text-anchor="start" x="711.56" y="-380.05" font-family="Arial" font-size="14.00" fill="#c9c9c9">runs &amp; rewrites URL</text>
</g>
<!-- supervisor&#45;&gt;flask -->
<g id="edge7" class="edge">
<title>supervisor&#45;&gt;flask</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M324.61,-452.6C346.19,-458.06 368.21,-462.78 389.43,-466 887.73,-541.72 1019.39,-479.32 1523.4,-478 1593.32,-477.82 1670.43,-477.45 1736.98,-477.07"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="1736.63,-479.7 1744.11,-477.03 1736.6,-474.45 1736.63,-479.7"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="1020.27,-498.92 1020.27,-521.72 1117.3,-521.72 1117.3,-498.92 1020.27,-498.92"/>
<text xml:space="preserve" text-anchor="start" x="1023.27" y="-504.72" font-family="Arial" font-size="14.00" fill="#c9c9c9">runs &amp; restarts</text>
</g>
<!-- tunnel&#45;&gt;flask -->
<g id="edge15" class="edge">
<title>tunnel&#45;&gt;flask</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M1523.14,-374.94C1590.34,-392.69 1668.71,-413.39 1736.96,-431.42"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="1736.1,-433.91 1744.02,-433.29 1737.44,-428.84 1736.1,-433.91"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="1590.02,-417.31 1590.02,-440.11 1680.07,-440.11 1680.07,-417.31 1590.02,-417.31"/>
<text xml:space="preserve" text-anchor="start" x="1593.02" y="-423.11" font-family="Arial" font-size="14.00" fill="#c9c9c9">proxies :5000</text>
</g>
<!-- flask&#45;&gt;jsonfiles -->
<g id="edge17" class="edge">
<title>flask&#45;&gt;jsonfiles</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M2066.46,-465.63C2086.73,-464.62 2107.21,-463.77 2126.72,-463.2 2206.83,-460.86 2226.94,-460.86 2307.05,-463.2 2322.89,-463.66 2339.37,-464.31 2355.86,-465.08"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="2355.48,-467.69 2363.1,-465.42 2355.74,-462.44 2355.48,-467.69"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="2151.24,-463.2 2151.24,-486 2282.53,-486 2282.53,-463.2 2151.24,-463.2"/>
<text xml:space="preserve" text-anchor="start" x="2154.24" y="-469" font-family="Arial" font-size="14.00" fill="#c9c9c9">serves at /api/&lt;key&gt;</text>
</g>
<!-- bot&#45;&gt;discord -->
<g id="edge10" class="edge">
<title>bot&#45;&gt;discord</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M1746.81,-854.06C1726.7,-850 1706.3,-846.53 1686.68,-844.2 1636.76,-838.27 1582.65,-842.22 1533.29,-849.9"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="1533.13,-847.27 1526.14,-851.05 1533.96,-852.45 1533.13,-847.27"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="1621.55,-844.2 1621.55,-867 1648.54,-867 1648.54,-844.2 1621.55,-844.2"/>
<text xml:space="preserve" text-anchor="start" x="1624.55" y="-852.4" font-family="Arial" font-weight="bold" font-size="14.00" fill="#c9c9c9">[...]</text>
</g>
<!-- bot&#45;&gt;maindb -->
<g id="edge11" class="edge">
<title>bot&#45;&gt;maindb</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M2015.06,-986.93C2126.01,-1079.87 2298.54,-1224.4 2411.92,-1319.38"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="2410.23,-1321.38 2417.66,-1324.19 2413.6,-1317.36 2410.23,-1321.38"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="2155.14,-1217.63 2155.14,-1240.43 2278.63,-1240.43 2278.63,-1217.63 2155.14,-1217.63"/>
<text xml:space="preserve" text-anchor="start" x="2158.14" y="-1223.43" font-family="Arial" font-size="14.00" fill="#c9c9c9">reads / writes state</text>
</g>
<!-- bot&#45;&gt;dmqueuedb -->
<g id="edge12" class="edge">
<title>bot&#45;&gt;dmqueuedb</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M2066.55,-862.32C2155.53,-842.89 2266.48,-818.67 2357.06,-798.9"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="2357.44,-801.5 2364.21,-797.34 2356.32,-796.37 2357.44,-801.5"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="2126.72,-845.56 2126.72,-868.36 2307.05,-868.36 2307.05,-845.56 2126.72,-845.56"/>
<text xml:space="preserve" text-anchor="start" x="2129.72" y="-851.36" font-family="Arial" font-size="14.00" fill="#c9c9c9">enqueues every user.send()</text>
</g>
<!-- bot&#45;&gt;trackers -->
<g id="edge13" class="edge">
<title>bot&#45;&gt;trackers</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M2066.55,-935.79C2155.53,-957.52 2266.48,-984.61 2357.06,-1006.73"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="2356.31,-1009.25 2364.22,-1008.48 2357.56,-1004.15 2356.31,-1009.25"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="2154.36,-990.47 2154.36,-1013.27 2279.41,-1013.27 2279.41,-990.47 2154.36,-990.47"/>
<text xml:space="preserve" text-anchor="start" x="2157.36" y="-996.27" font-family="Arial" font-size="14.00" fill="#c9c9c9">shells out to scripts</text>
</g>
<!-- bot&#45;&gt;jsonfiles -->
<g id="edge14" class="edge">
<title>bot&#45;&gt;jsonfiles</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M1992.89,-807.07C2031.67,-768.82 2079.41,-725.28 2126.72,-691.2 2198.27,-639.66 2283.62,-592.04 2357.01,-554.77"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="2358.15,-557.13 2363.66,-551.41 2355.78,-552.45 2358.15,-557.13"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="2145.03,-691.2 2145.03,-714 2288.74,-714 2288.74,-691.2 2145.03,-691.2"/>
<text xml:space="preserve" text-anchor="start" x="2148.03" y="-697" font-family="Arial" font-size="14.00" fill="#c9c9c9">writes per&#45;page JSON</text>
</g>
</g>
</svg>
`;case`view_na89us`:return`<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"
 "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
<!-- Generated by graphviz version 14.1.5 (0)
 -->
<!-- Pages: 1 -->
<svg width="2440pt" height="973pt"
 viewBox="0.00 0.00 2440.00 973.00" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
<g id="graph0" class="graph" transform="scale(1 1) rotate(0) translate(15.05 957.85)">
<g id="clust1" class="cluster">
<title>cluster_bot</title>
<polygon fill="#194b9e" stroke="#1b3d88" points="360.02,-8 360.02,-934.8 1190.02,-934.8 1190.02,-8 360.02,-8"/>
<text xml:space="preserve" text-anchor="start" x="368.02" y="-921.9" font-family="Arial" font-weight="bold" font-size="11.00" fill="#bfdbfe" fill-opacity="0.701961">WAVE MANAGEMENT BOT</text>
</g>
<!-- main -->
<g id="node1" class="node">
<title>main</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="1092.04,-873.6 772,-873.6 772,-693.6 1092.04,-693.6 1092.04,-873.6"/>
<text xml:space="preserve" text-anchor="start" x="897.01" y="-786.6" font-family="Arial" font-size="20.00" fill="#eff6ff">main.py</text>
<text xml:space="preserve" text-anchor="start" x="896.17" y="-763.6" font-family="Arial" font-size="15.00" fill="#bfdbfe">Entry point</text>
</g>
<!-- cogs -->
<g id="node2" class="node">
<title>cogs</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="720.04,-550.8 400,-550.8 400,-370.8 720.04,-370.8 720.04,-550.8"/>
<text xml:space="preserve" text-anchor="start" x="484.43" y="-463.8" font-family="Arial" font-size="20.00" fill="#eff6ff">commands/ cogs</text>
<text xml:space="preserve" text-anchor="start" x="480.41" y="-440.8" font-family="Arial" font-size="15.00" fill="#bfdbfe">Game &amp; admin systems</text>
</g>
<!-- tasks -->
<g id="node3" class="node">
<title>tasks</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="1150.04,-550.8 830,-550.8 830,-370.8 1150.04,-370.8 1150.04,-550.8"/>
<text xml:space="preserve" text-anchor="start" x="882.18" y="-463.8" font-family="Arial" font-size="20.00" fill="#eff6ff">tasks/ background loops</text>
<text xml:space="preserve" text-anchor="start" x="904.96" y="-440.8" font-family="Arial" font-size="15.00" fill="#bfdbfe">Scheduled jobs &amp; queues</text>
</g>
<!-- core -->
<g id="node4" class="node">
<title>core</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="1035.04,-228 715,-228 715,-48 1035.04,-48 1035.04,-228"/>
<text xml:space="preserve" text-anchor="start" x="817.21" y="-141" font-family="Arial" font-size="20.00" fill="#eff6ff">core/ helpers</text>
<text xml:space="preserve" text-anchor="start" x="794.97" y="-118" font-family="Arial" font-size="15.00" fill="#bfdbfe">Shared helpers &amp; config</text>
</g>
<!-- discord -->
<g id="node5" class="node">
<title>discord</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="320.04,-228 0,-228 0,-48 320.04,-48 320.04,-228"/>
<text xml:space="preserve" text-anchor="start" x="126.12" y="-141" font-family="Arial" font-size="20.00" fill="#eff6ff">Discord</text>
<text xml:space="preserve" text-anchor="start" x="43.71" y="-118" font-family="Arial" font-size="15.00" fill="#bfdbfe">discord.py gateway across 3 guilds</text>
</g>
<!-- dmqueuedb -->
<g id="node6" class="node">
<title>dmqueuedb</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="1580.04,-546.8 1260,-546.8 1260,-374.8 1580.04,-374.8 1580.04,-546.8"/>
<text xml:space="preserve" text-anchor="start" x="1322.72" y="-473.6" font-family="Arial" font-size="20.00" fill="#eff6ff">dm_shared_queue.db</text>
<text xml:space="preserve" text-anchor="start" x="1357.16" y="-452.6" font-family="Arial" font-size="13.00" fill="#bfdbfe">SQLite on C:/Desktop</text>
<text xml:space="preserve" text-anchor="start" x="1350.82" y="-431" font-family="Arial" font-size="15.00" fill="#bfdbfe">Cross&#45;bot DM queue</text>
</g>
<!-- trackers -->
<g id="node7" class="node">
<title>trackers</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="1550.04,-228 1230,-228 1230,-48 1550.04,-48 1550.04,-228"/>
<text xml:space="preserve" text-anchor="start" x="1304.44" y="-141" font-family="Arial" font-size="20.00" fill="#eff6ff">command&#45;trackers/</text>
<text xml:space="preserve" text-anchor="start" x="1298.72" y="-118" font-family="Arial" font-size="15.00" fill="#bfdbfe">Data trackers shelled out to</text>
</g>
<!-- maindb -->
<g id="node8" class="node">
<title>maindb</title>
<path fill="#3b82f6" stroke="#2563eb" stroke-width="2" d="M1980.04,-211.64C1980.04,-220.67 1908.32,-228 1820.02,-228 1731.72,-228 1660,-220.67 1660,-211.64 1660,-211.64 1660,-64.36 1660,-64.36 1660,-55.33 1731.72,-48 1820.02,-48 1908.32,-48 1980.04,-55.33 1980.04,-64.36 1980.04,-64.36 1980.04,-211.64 1980.04,-211.64"/>
<path fill="none" stroke="#2563eb" stroke-width="2" d="M1980.04,-211.64C1980.04,-202.61 1908.32,-195.27 1820.02,-195.27 1731.72,-195.27 1660,-202.61 1660,-211.64"/>
<text xml:space="preserve" text-anchor="start" x="1745.51" y="-150.8" font-family="Arial" font-size="20.00" fill="#eff6ff">bot_database.db</text>
<text xml:space="preserve" text-anchor="start" x="1740.54" y="-129.8" font-family="Arial" font-size="13.00" fill="#bfdbfe">SQLite · WAL · async pool</text>
<text xml:space="preserve" text-anchor="start" x="1749.15" y="-108.2" font-family="Arial" font-size="15.00" fill="#bfdbfe">Single source of truth</text>
</g>
<!-- jsonfiles -->
<g id="node9" class="node">
<title>jsonfiles</title>
<path fill="#3b82f6" stroke="#2563eb" stroke-width="2" d="M2410.04,-211.64C2410.04,-220.67 2338.32,-228 2250.02,-228 2161.72,-228 2090,-220.67 2090,-211.64 2090,-211.64 2090,-64.36 2090,-64.36 2090,-55.33 2161.72,-48 2250.02,-48 2338.32,-48 2410.04,-55.33 2410.04,-64.36 2410.04,-64.36 2410.04,-211.64 2410.04,-211.64"/>
<path fill="none" stroke="#2563eb" stroke-width="2" d="M2410.04,-211.64C2410.04,-202.61 2338.32,-195.27 2250.02,-195.27 2161.72,-195.27 2090,-202.61 2090,-211.64"/>
<text xml:space="preserve" text-anchor="start" x="2166.08" y="-141" font-family="Arial" font-size="20.00" fill="#eff6ff">website/data/*.json</text>
<text xml:space="preserve" text-anchor="start" x="2190.4" y="-118" font-family="Arial" font-size="15.00" fill="#bfdbfe">Bot&#45;built payloads</text>
</g>
<!-- main&#45;&gt;cogs -->
<g id="edge4" class="edge">
<title>main&#45;&gt;cogs</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M826.93,-693.82C803.68,-674.06 779.21,-653.17 756.5,-633.6 727.91,-608.96 697.11,-582.17 668.58,-557.23"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="670.65,-555.54 663.27,-552.58 667.19,-559.49 670.65,-555.54"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="756.5,-610.8 756.5,-633.6 880.02,-633.6 880.02,-610.8 756.5,-610.8"/>
<text xml:space="preserve" text-anchor="start" x="759.5" y="-616.6" font-family="Arial" font-size="14.00" fill="#c9c9c9">loads &amp; dispatches</text>
</g>
<!-- main&#45;&gt;tasks -->
<g id="edge5" class="edge">
<title>main&#45;&gt;tasks</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M908.46,-694.01C904.61,-667.04 903.75,-637.48 910.43,-610.8 914.73,-593.64 921.42,-576.29 929.14,-559.8"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="931.31,-561.35 932.21,-553.45 926.58,-559.06 931.31,-561.35"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="910.43,-610.8 910.43,-633.6 988.02,-633.6 988.02,-610.8 910.43,-610.8"/>
<text xml:space="preserve" text-anchor="start" x="913.43" y="-616.6" font-family="Arial" font-size="14.00" fill="#c9c9c9">starts loops</text>
</g>
<!-- main&#45;&gt;dmqueuedb -->
<g id="edge3" class="edge">
<title>main&#45;&gt;dmqueuedb</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M1006.17,-693.99C1033.28,-665.08 1065.49,-634.38 1098.7,-610.8 1113.3,-600.43 1181.18,-568.63 1250.81,-537.06"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="1251.68,-539.55 1257.43,-534.06 1249.52,-534.76 1251.68,-539.55"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="1098.7,-610.8 1098.7,-633.6 1279.02,-633.6 1279.02,-610.8 1098.7,-610.8"/>
<text xml:space="preserve" text-anchor="start" x="1101.7" y="-616.6" font-family="Arial" font-size="14.00" fill="#c9c9c9">enqueues every user.send()</text>
</g>
<!-- cogs&#45;&gt;core -->
<g id="edge8" class="edge">
<title>cogs&#45;&gt;core</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M647.35,-370.87C688.74,-328.71 738.26,-278.27 780.54,-235.22"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="782.29,-237.18 785.68,-229.99 778.55,-233.5 782.29,-237.18"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="726.96,-288 726.96,-310.8 812.34,-310.8 812.34,-288 726.96,-288"/>
<text xml:space="preserve" text-anchor="start" x="729.96" y="-293.8" font-family="Arial" font-size="14.00" fill="#c9c9c9">uses helpers</text>
</g>
<!-- cogs&#45;&gt;discord -->
<g id="edge6" class="edge">
<title>cogs&#45;&gt;discord</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M400.06,-434.42C323.54,-413.92 237.4,-377.03 185.07,-310.8 168.82,-290.23 160.72,-263.82 157.11,-237.9"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="159.73,-237.76 156.25,-230.62 154.52,-238.38 159.73,-237.76"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="185.07,-288 185.07,-310.8 328.02,-310.8 328.02,-288 185.07,-288"/>
<text xml:space="preserve" text-anchor="start" x="188.07" y="-293.8" font-family="Arial" font-size="14.00" fill="#c9c9c9">replies, roles, embeds</text>
</g>
<!-- cogs&#45;&gt;trackers -->
<g id="edge7" class="edge">
<title>cogs&#45;&gt;trackers</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M720.01,-389.97C738.4,-383.02 757,-376.46 775.02,-370.8 893.54,-333.56 930.74,-351.75 1048.02,-310.8 1126.99,-283.23 1142.27,-265.53 1217.02,-228 1218.39,-227.31 1219.76,-226.62 1221.14,-225.93"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="1222.09,-228.39 1227.6,-222.67 1219.73,-223.7 1222.09,-228.39"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="1102.08,-288 1102.08,-310.8 1227.12,-310.8 1227.12,-288 1102.08,-288"/>
<text xml:space="preserve" text-anchor="start" x="1105.08" y="-293.8" font-family="Arial" font-size="14.00" fill="#c9c9c9">shells out to scripts</text>
</g>
<!-- cogs&#45;&gt;maindb -->
<g id="edge9" class="edge">
<title>cogs&#45;&gt;maindb</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M719.83,-388.19C738.2,-381.6 756.86,-375.6 775.02,-370.8 982.44,-315.94 1042.86,-348.82 1254.02,-310.8 1411.77,-282.4 1452.48,-277.21 1605.02,-228 1619.53,-223.32 1634.43,-218.09 1649.29,-212.56"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="1650.12,-215.06 1656.22,-209.96 1648.28,-210.14 1650.12,-215.06"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="1377,-288 1377,-310.8 1500.49,-310.8 1500.49,-288 1377,-288"/>
<text xml:space="preserve" text-anchor="start" x="1380" y="-293.8" font-family="Arial" font-size="14.00" fill="#c9c9c9">reads / writes state</text>
</g>
<!-- tasks&#45;&gt;core -->
<g id="edge11" class="edge">
<title>tasks&#45;&gt;core</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M958.14,-370.87C943.31,-329.49 925.62,-280.15 910.38,-237.63"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="912.89,-236.85 907.89,-230.68 907.94,-238.62 912.89,-236.85"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="935.97,-288 935.97,-310.8 1021.35,-310.8 1021.35,-288 935.97,-288"/>
<text xml:space="preserve" text-anchor="start" x="938.97" y="-293.8" font-family="Arial" font-size="14.00" fill="#c9c9c9">uses helpers</text>
</g>
<!-- tasks&#45;&gt;discord -->
<g id="edge10" class="edge">
<title>tasks&#45;&gt;discord</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M830.14,-389.58C811.74,-382.71 793.1,-376.27 775.02,-370.8 643.26,-330.95 600.49,-357.97 471.17,-310.8 415.79,-290.61 358.43,-261.56 308.26,-233.09"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="309.75,-230.92 301.94,-229.47 307.14,-235.47 309.75,-230.92"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="471.17,-288 471.17,-310.8 681.02,-310.8 681.02,-288 471.17,-288"/>
<text xml:space="preserve" text-anchor="start" x="474.17" y="-293.8" font-family="Arial" font-size="14.00" fill="#c9c9c9">posts leaderboards, strikes, DMs</text>
</g>
<!-- tasks&#45;&gt;maindb -->
<g id="edge12" class="edge">
<title>tasks&#45;&gt;maindb</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M1149.8,-388.09C1168.18,-381.52 1186.85,-375.55 1205.02,-370.8 1421.98,-314.05 1515.08,-428.41 1706.02,-310.8 1734.61,-293.19 1757.55,-265.42 1775.15,-237.3"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="1777.22,-238.94 1778.87,-231.17 1772.73,-236.22 1777.22,-238.94"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="1732.3,-288 1732.3,-310.8 1855.79,-310.8 1855.79,-288 1732.3,-288"/>
<text xml:space="preserve" text-anchor="start" x="1735.3" y="-293.8" font-family="Arial" font-size="14.00" fill="#c9c9c9">reads / writes state</text>
</g>
<!-- tasks&#45;&gt;jsonfiles -->
<g id="edge13" class="edge">
<title>tasks&#45;&gt;jsonfiles</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M1149.96,-387.42C1168.27,-380.99 1186.87,-375.25 1205.02,-370.8 1498.83,-298.78 1590.91,-389.46 1883.02,-310.8 1954.57,-291.53 2029.36,-259.04 2092.62,-227.47"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="2093.64,-229.89 2099.16,-224.18 2091.28,-225.2 2093.64,-229.89"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="1946.09,-288 1946.09,-310.8 2089.8,-310.8 2089.8,-288 1946.09,-288"/>
<text xml:space="preserve" text-anchor="start" x="1949.09" y="-293.8" font-family="Arial" font-size="14.00" fill="#c9c9c9">writes per&#45;page JSON</text>
</g>
<!-- discord&#45;&gt;main -->
<g id="edge1" class="edge">
<title>discord&#45;&gt;main</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M150.29,-227.94C148.51,-247.69 146.93,-268.53 146.02,-288 140.2,-412.17 151.43,-465.38 241.74,-550.8 384.51,-685.86 608.44,-742.36 762.31,-765.92"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="761.54,-768.46 769.35,-766.97 762.32,-763.27 761.54,-768.46"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="241.74,-449.4 241.74,-472.2 345.02,-472.2 345.02,-449.4 241.74,-449.4"/>
<text xml:space="preserve" text-anchor="start" x="244.74" y="-455.2" font-family="Arial" font-size="14.00" fill="#c9c9c9">gateway events</text>
</g>
<!-- dmqueuedb&#45;&gt;main -->
<g id="edge2" class="edge">
<title>dmqueuedb&#45;&gt;main</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M1377.74,-546.76C1359.15,-577.38 1334.92,-610.13 1306.02,-633.6 1246.81,-681.68 1170.13,-715.84 1101.63,-739.21"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="1101.16,-736.6 1094.89,-741.48 1102.83,-741.58 1101.16,-736.6"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="1326.5,-610.8 1326.5,-633.6 1483.42,-633.6 1483.42,-610.8 1326.5,-610.8"/>
<text xml:space="preserve" text-anchor="start" x="1329.5" y="-616.6" font-family="Arial" font-size="14.00" fill="#c9c9c9">worker claims &amp; delivers</text>
</g>
</g>
</svg>
`;case`website`:return`<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"
 "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
<!-- Generated by graphviz version 14.1.5 (0)
 -->
<!-- Pages: 1 -->
<svg width="2451pt" height="1270pt"
 viewBox="0.00 0.00 2451.00 1270.00" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
<g id="graph0" class="graph" transform="scale(1 1) rotate(0) translate(15.05 1255.05)">
<g id="clust1" class="cluster">
<title>cluster_bot</title>
<polygon fill="#194b9e" stroke="#1b3d88" points="1485.6,-967 1485.6,-1232 1869.64,-1232 1869.64,-967 1485.6,-967"/>
<text xml:space="preserve" text-anchor="start" x="1493.6" y="-1219.1" font-family="Arial" font-weight="bold" font-size="11.00" fill="#bfdbfe" fill-opacity="0.701961">WAVE MANAGEMENT BOT</text>
</g>
<g id="clust2" class="cluster">
<title>cluster_edge</title>
<polygon fill="#194b9e" stroke="#1b3d88" points="410.43,-8 410.43,-579 810.47,-579 810.47,-8 410.43,-8"/>
<text xml:space="preserve" text-anchor="start" x="418.43" y="-566.1" font-family="Arial" font-weight="bold" font-size="11.00" fill="#bfdbfe" fill-opacity="0.701961">CLOUDFLARE PAGES</text>
</g>
<!-- tasks -->
<g id="node1" class="node">
<title>tasks</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="1837.64,-1179 1517.6,-1179 1517.6,-999 1837.64,-999 1837.64,-1179"/>
<text xml:space="preserve" text-anchor="start" x="1569.77" y="-1092" font-family="Arial" font-size="20.00" fill="#eff6ff">tasks/ background loops</text>
<text xml:space="preserve" text-anchor="start" x="1592.55" y="-1069" font-family="Arial" font-size="15.00" fill="#bfdbfe">Scheduled jobs &amp; queues</text>
</g>
<!-- hub -->
<g id="node2" class="node">
<title>hub</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="770.47,-228 450.43,-228 450.43,-48 770.47,-48 770.47,-228"/>
<text xml:space="preserve" text-anchor="start" x="493.72" y="-141" font-family="Arial" font-size="20.00" fill="#eff6ff">wavedropmaps.pages.dev</text>
<text xml:space="preserve" text-anchor="start" x="478.71" y="-118" font-family="Arial" font-size="15.00" fill="#bfdbfe">Wave Staff Hub — 9 leaderboard pages</text>
</g>
<!-- logsite -->
<g id="node3" class="node">
<title>logsite</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="770.47,-518 450.43,-518 450.43,-338 770.47,-338 770.47,-518"/>
<text xml:space="preserve" text-anchor="start" x="502.6" y="-431" font-family="Arial" font-size="20.00" fill="#eff6ff">wave&#45;logging.pages.dev</text>
<text xml:space="preserve" text-anchor="start" x="524.56" y="-408" font-family="Arial" font-size="15.00" fill="#bfdbfe">Wave&#45;Logging dashboard</text>
</g>
<!-- supervisor -->
<g id="node4" class="node">
<title>supervisor</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="324.74,-828 4.7,-828 4.7,-648 324.74,-648 324.74,-828"/>
<text xml:space="preserve" text-anchor="start" x="80.22" y="-741" font-family="Arial" font-size="20.00" fill="#eff6ff">staff_hub_serve.py</text>
<text xml:space="preserve" text-anchor="start" x="128.87" y="-718" font-family="Arial" font-size="15.00" fill="#bfdbfe">Supervisor</text>
</g>
<!-- tunnel -->
<g id="node5" class="node">
<title>tunnel</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="1307.54,-761 987.5,-761 987.5,-581 1307.54,-581 1307.54,-761"/>
<text xml:space="preserve" text-anchor="start" x="1068.58" y="-674" font-family="Arial" font-size="20.00" fill="#eff6ff">cloudflared tunnel</text>
<text xml:space="preserve" text-anchor="start" x="1105.83" y="-651" font-family="Arial" font-size="15.00" fill="#bfdbfe">Quick tunnel</text>
</g>
<!-- flask -->
<g id="node6" class="node">
<title>flask</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="1837.64,-889 1517.6,-889 1517.6,-709 1837.64,-709 1837.64,-889"/>
<text xml:space="preserve" text-anchor="start" x="1627.02" y="-802" font-family="Arial" font-size="20.00" fill="#eff6ff">web_api.py</text>
<text xml:space="preserve" text-anchor="start" x="1577.44" y="-779" font-family="Arial" font-size="15.00" fill="#bfdbfe">Flask origin @ 127.0.0.1:5000</text>
</g>
<!-- viewer -->
<g id="node7" class="node">
<title>viewer</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="329.43,-228 0,-228 0,-48 329.43,-48 329.43,-228"/>
<text xml:space="preserve" text-anchor="start" x="114.7" y="-150" font-family="Arial" font-size="20.00" fill="#eff6ff">Hub viewer</text>
<text xml:space="preserve" text-anchor="start" x="20.06" y="-127" font-family="Arial" font-size="15.00" fill="#bfdbfe">Staff member viewing the leaderboards in a</text>
<text xml:space="preserve" text-anchor="start" x="138.04" y="-109" font-family="Arial" font-size="15.00" fill="#bfdbfe">browser</text>
</g>
<!-- jsonfiles -->
<g id="node8" class="node">
<title>jsonfiles</title>
<path fill="#3b82f6" stroke="#2563eb" stroke-width="2" d="M2421.39,-872.64C2421.39,-881.67 2349.67,-889 2261.37,-889 2173.08,-889 2101.35,-881.67 2101.35,-872.64 2101.35,-872.64 2101.35,-725.36 2101.35,-725.36 2101.35,-716.33 2173.08,-709 2261.37,-709 2349.67,-709 2421.39,-716.33 2421.39,-725.36 2421.39,-725.36 2421.39,-872.64 2421.39,-872.64"/>
<path fill="none" stroke="#2563eb" stroke-width="2" d="M2421.39,-872.64C2421.39,-863.61 2349.67,-856.27 2261.37,-856.27 2173.08,-856.27 2101.35,-863.61 2101.35,-872.64"/>
<text xml:space="preserve" text-anchor="start" x="2177.43" y="-802" font-family="Arial" font-size="20.00" fill="#eff6ff">website/data/*.json</text>
<text xml:space="preserve" text-anchor="start" x="2201.75" y="-779" font-family="Arial" font-size="15.00" fill="#bfdbfe">Bot&#45;built payloads</text>
</g>
<!-- tasks&#45;&gt;jsonfiles -->
<g id="edge5" class="edge">
<title>tasks&#45;&gt;jsonfiles</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M1837.58,-1009.76C1916.3,-970.52 2011.37,-923.13 2091.4,-883.23"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="2092.34,-885.7 2097.88,-880 2089.99,-881 2092.34,-885.7"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="1897.64,-978.5 1897.64,-1001.3 2041.35,-1001.3 2041.35,-978.5 1897.64,-978.5"/>
<text xml:space="preserve" text-anchor="start" x="1900.64" y="-984.3" font-family="Arial" font-size="14.00" fill="#c9c9c9">writes per&#45;page JSON</text>
</g>
<!-- logsite&#45;&gt;tunnel -->
<g id="edge8" class="edge">
<title>logsite&#45;&gt;tunnel</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M810.47,-518.38C865.74,-543.49 925.2,-570.49 978.51,-594.7"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="977.17,-596.97 985.08,-597.68 979.34,-592.19 977.17,-596.97"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="750.07,-535.89 750.07,-558.69 899.23,-558.69 899.23,-535.89 750.07,-535.89"/>
<text xml:space="preserve" text-anchor="start" x="753.07" y="-541.69" font-family="Arial" font-size="14.00" fill="#c9c9c9">proxies with X&#45;API&#45;Key</text>
</g>
<!-- supervisor&#45;&gt;hub -->
<g id="edge3" class="edge">
<title>supervisor&#45;&gt;hub</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M199.8,-648.23C238.89,-553.11 309.87,-401.66 403.64,-290.9"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="405.56,-292.7 408.46,-285.3 401.58,-289.27 405.56,-292.7"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="126.12,-435.08 126.12,-457.88 290.85,-457.88 290.85,-435.08 126.12,-435.08"/>
<text xml:space="preserve" text-anchor="start" x="129.12" y="-440.88" font-family="Arial" font-size="14.00" fill="#c9c9c9">wrangler deploys workers</text>
</g>
<!-- supervisor&#45;&gt;tunnel -->
<g id="edge1" class="edge">
<title>supervisor&#45;&gt;tunnel</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M324.66,-727.14C503.9,-714.9 794.2,-695.07 977.48,-682.55"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="977.44,-685.18 984.74,-682.05 977.08,-679.94 977.44,-685.18"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="544.83,-721.25 544.83,-744.05 676.08,-744.05 676.08,-721.25 544.83,-721.25"/>
<text xml:space="preserve" text-anchor="start" x="547.83" y="-727.05" font-family="Arial" font-size="14.00" fill="#c9c9c9">runs &amp; rewrites URL</text>
</g>
<!-- supervisor&#45;&gt;flask -->
<g id="edge2" class="edge">
<title>supervisor&#45;&gt;flask</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M324.54,-792.16C346.14,-797.79 368.18,-802.66 389.43,-806 792.56,-869.36 899.58,-825.39 1307.54,-816 1372.84,-814.5 1444.59,-811.5 1507.32,-808.43"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="1507.33,-811.06 1514.69,-808.07 1507.07,-805.82 1507.33,-811.06"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="830.47,-838.65 830.47,-861.45 927.5,-861.45 927.5,-838.65 830.47,-838.65"/>
<text xml:space="preserve" text-anchor="start" x="833.47" y="-844.45" font-family="Arial" font-size="14.00" fill="#c9c9c9">runs &amp; restarts</text>
</g>
<!-- tunnel&#45;&gt;flask -->
<g id="edge6" class="edge">
<title>tunnel&#45;&gt;flask</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M1307.32,-709.49C1370.74,-724.86 1443.85,-742.58 1508.19,-758.18"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="1507.18,-760.63 1515.09,-759.85 1508.42,-755.53 1507.18,-760.63"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="1367.54,-742.66 1367.54,-765.46 1457.6,-765.46 1457.6,-742.66 1367.54,-742.66"/>
<text xml:space="preserve" text-anchor="start" x="1370.54" y="-748.46" font-family="Arial" font-size="14.00" fill="#c9c9c9">proxies :5000</text>
</g>
<!-- flask&#45;&gt;jsonfiles -->
<g id="edge7" class="edge">
<title>flask&#45;&gt;jsonfiles</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M1837.58,-799C1915.98,-799 2010.6,-799 2090.43,-799"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="2090.06,-801.63 2097.56,-799 2090.06,-796.38 2090.06,-801.63"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="1903.85,-799 1903.85,-821.8 2035.14,-821.8 2035.14,-799 1903.85,-799"/>
<text xml:space="preserve" text-anchor="start" x="1906.85" y="-804.8" font-family="Arial" font-size="14.00" fill="#c9c9c9">serves at /api/&lt;key&gt;</text>
</g>
<!-- viewer&#45;&gt;hub -->
<g id="edge4" class="edge">
<title>viewer&#45;&gt;hub</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M329.37,-138C352.36,-138 376.24,-138 399.93,-138"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="399.91,-140.63 407.41,-138 399.91,-135.38 399.91,-140.63"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="369.93,-126.6 369.93,-149.4 509.79,-149.4 509.79,-126.6 369.93,-126.6"/>
<text xml:space="preserve" text-anchor="start" x="372.93" y="-132.4" font-family="Arial" font-size="14.00" fill="#c9c9c9">opens hub in browser</text>
</g>
</g>
</svg>
`;case`crossbot`:return`<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN"
 "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">
<!-- Generated by graphviz version 14.1.5 (0)
 -->
<!-- Pages: 1 -->
<svg width="2081pt" height="674pt"
 viewBox="0.00 0.00 2081.00 674.00" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
<g id="graph0" class="graph" transform="scale(1 1) rotate(0) translate(15.05 659.05)">
<g id="clust1" class="cluster">
<title>cluster_bot</title>
<polygon fill="#194b9e" stroke="#1b3d88" points="1069.02,-8 1069.02,-273 1453.06,-273 1453.06,-8 1069.02,-8"/>
<text xml:space="preserve" text-anchor="start" x="1077.02" y="-260.1" font-family="Arial" font-weight="bold" font-size="11.00" fill="#bfdbfe" fill-opacity="0.701961">WAVE MANAGEMENT BOT</text>
</g>
<!-- main -->
<g id="node1" class="node">
<title>main</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="1421.06,-220 1101.02,-220 1101.02,-40 1421.06,-40 1421.06,-220"/>
<text xml:space="preserve" text-anchor="start" x="1226.03" y="-133" font-family="Arial" font-size="20.00" fill="#eff6ff">main.py</text>
<text xml:space="preserve" text-anchor="start" x="1225.19" y="-110" font-family="Arial" font-size="15.00" fill="#bfdbfe">Entry point</text>
</g>
<!-- staff -->
<g id="node2" class="node">
<title>staff</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="320.04,-220 0,-220 0,-40 320.04,-40 320.04,-220"/>
<text xml:space="preserve" text-anchor="start" x="100" y="-142" font-family="Arial" font-size="20.00" fill="#eff6ff">Staff member</text>
<text xml:space="preserve" text-anchor="start" x="20.37" y="-119" font-family="Arial" font-size="15.00" fill="#bfdbfe">Drop&#45;map staff across the 3 guilds — earn</text>
<text xml:space="preserve" text-anchor="start" x="65.82" y="-101" font-family="Arial" font-size="15.00" fill="#bfdbfe">points, get strikes &amp; rewards</text>
</g>
<!-- discord -->
<g id="node3" class="node">
<title>discord</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="877.74,-220 557.7,-220 557.7,-40 877.74,-40 877.74,-220"/>
<text xml:space="preserve" text-anchor="start" x="683.82" y="-133" font-family="Arial" font-size="20.00" fill="#eff6ff">Discord</text>
<text xml:space="preserve" text-anchor="start" x="601.41" y="-110" font-family="Arial" font-size="15.00" fill="#bfdbfe">discord.py gateway across 3 guilds</text>
</g>
<!-- logistics -->
<g id="node4" class="node">
<title>logistics</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="1421.06,-510 1101.02,-510 1101.02,-330 1421.06,-330 1421.06,-510"/>
<text xml:space="preserve" text-anchor="start" x="1176.01" y="-423" font-family="Arial" font-size="20.00" fill="#eff6ff">Wave Logistics Bot</text>
<text xml:space="preserve" text-anchor="start" x="1152.22" y="-400" font-family="Arial" font-size="15.00" fill="#bfdbfe">Sibling bot on the same machine</text>
</g>
<!-- maindb -->
<g id="node5" class="node">
<title>maindb</title>
<path fill="#3b82f6" stroke="#2563eb" stroke-width="2" d="M2050.79,-627.64C2050.79,-636.67 1979.07,-644 1890.77,-644 1802.47,-644 1730.75,-636.67 1730.75,-627.64 1730.75,-627.64 1730.75,-480.36 1730.75,-480.36 1730.75,-471.33 1802.47,-464 1890.77,-464 1979.07,-464 2050.79,-471.33 2050.79,-480.36 2050.79,-480.36 2050.79,-627.64 2050.79,-627.64"/>
<path fill="none" stroke="#2563eb" stroke-width="2" d="M2050.79,-627.64C2050.79,-618.61 1979.07,-611.27 1890.77,-611.27 1802.47,-611.27 1730.75,-618.61 1730.75,-627.64"/>
<text xml:space="preserve" text-anchor="start" x="1816.26" y="-566.8" font-family="Arial" font-size="20.00" fill="#eff6ff">bot_database.db</text>
<text xml:space="preserve" text-anchor="start" x="1811.29" y="-545.8" font-family="Arial" font-size="13.00" fill="#bfdbfe">SQLite · WAL · async pool</text>
<text xml:space="preserve" text-anchor="start" x="1819.9" y="-524.2" font-family="Arial" font-size="15.00" fill="#bfdbfe">Single source of truth</text>
</g>
<!-- dmqueuedb -->
<g id="node6" class="node">
<title>dmqueuedb</title>
<polygon fill="#3b82f6" stroke="#2563eb" stroke-width="0" points="2050.79,-354 1730.75,-354 1730.75,-182 2050.79,-182 2050.79,-354"/>
<text xml:space="preserve" text-anchor="start" x="1793.47" y="-280.8" font-family="Arial" font-size="20.00" fill="#eff6ff">dm_shared_queue.db</text>
<text xml:space="preserve" text-anchor="start" x="1827.9" y="-259.8" font-family="Arial" font-size="13.00" fill="#bfdbfe">SQLite on C:/Desktop</text>
<text xml:space="preserve" text-anchor="start" x="1821.57" y="-238.2" font-family="Arial" font-size="15.00" fill="#bfdbfe">Cross&#45;bot DM queue</text>
</g>
<!-- main&#45;&gt;dmqueuedb -->
<g id="edge5" class="edge">
<title>main&#45;&gt;dmqueuedb</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M1420.85,-164.91C1512.4,-185.04 1627.46,-210.33 1720.7,-230.83"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="1719.95,-233.36 1727.84,-232.4 1721.08,-228.23 1719.95,-233.36"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="1485.74,-219.42 1485.74,-242.22 1666.07,-242.22 1666.07,-219.42 1485.74,-219.42"/>
<text xml:space="preserve" text-anchor="start" x="1488.74" y="-225.22" font-family="Arial" font-size="14.00" fill="#c9c9c9">enqueues every user.send()</text>
</g>
<!-- staff&#45;&gt;discord -->
<g id="edge1" class="edge">
<title>staff&#45;&gt;discord</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M319.89,-130C391.12,-130 475.2,-130 547.6,-130"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="547.2,-132.63 554.7,-130 547.2,-127.38 547.2,-132.63"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="380.04,-130 380.04,-152.8 497.7,-152.8 497.7,-130 380.04,-130"/>
<text xml:space="preserve" text-anchor="start" x="383.04" y="-135.8" font-family="Arial" font-size="14.00" fill="#c9c9c9">runs &gt; commands</text>
</g>
<!-- discord&#45;&gt;main -->
<g id="edge4" class="edge">
<title>discord&#45;&gt;main</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M877.48,-130C944.54,-130 1022.72,-130 1090.87,-130"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="1090.76,-132.63 1098.26,-130 1090.76,-127.38 1090.76,-132.63"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="937.74,-130 937.74,-152.8 1041.02,-152.8 1041.02,-130 937.74,-130"/>
<text xml:space="preserve" text-anchor="start" x="940.74" y="-135.8" font-family="Arial" font-size="14.00" fill="#c9c9c9">gateway events</text>
</g>
<!-- logistics&#45;&gt;maindb -->
<g id="edge2" class="edge">
<title>logistics&#45;&gt;maindb</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M1420.85,-453.9C1512.14,-473.39 1626.8,-497.87 1719.89,-517.74"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="1719.14,-520.26 1727.02,-519.26 1720.23,-515.13 1719.14,-520.26"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="1481.06,-506.83 1481.06,-529.63 1670.75,-529.63 1670.75,-506.83 1481.06,-506.83"/>
<text xml:space="preserve" text-anchor="start" x="1484.06" y="-512.63" font-family="Arial" font-size="14.00" fill="#c9c9c9">feeds loot/surge queue codes</text>
</g>
<!-- logistics&#45;&gt;dmqueuedb -->
<g id="edge3" class="edge">
<title>logistics&#45;&gt;dmqueuedb</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M1420.85,-381.55C1512.4,-359.38 1627.46,-331.52 1720.7,-308.94"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="1721.18,-311.52 1727.86,-307.21 1719.95,-306.42 1721.18,-311.52"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="1518.81,-366.5 1518.81,-389.3 1633,-389.3 1633,-366.5 1518.81,-366.5"/>
<text xml:space="preserve" text-anchor="start" x="1521.81" y="-372.3" font-family="Arial" font-size="14.00" fill="#c9c9c9">shares the queue</text>
</g>
<!-- dmqueuedb&#45;&gt;main -->
<g id="edge6" class="edge">
<title>dmqueuedb&#45;&gt;main</title>
<path fill="none" stroke="#8d8d8d" stroke-width="2" stroke-dasharray="5,2" d="M1780.88,-182.12C1747.42,-160.54 1709.23,-140.37 1670.75,-129.2 1594.11,-106.96 1505.93,-104.42 1431.15,-108.55"/>
<polygon fill="#8d8d8d" stroke="#8d8d8d" stroke-width="2" points="1431.03,-105.93 1423.71,-109 1431.35,-111.17 1431.03,-105.93"/>
<polygon fill="#18191b" fill-opacity="0.627451" stroke="none" points="1497.44,-129.2 1497.44,-152 1654.37,-152 1654.37,-129.2 1497.44,-129.2"/>
<text xml:space="preserve" text-anchor="start" x="1500.44" y="-135" font-family="Arial" font-size="14.00" fill="#c9c9c9">worker claims &amp; delivers</text>
</g>
</g>
</svg>
`;default:throw Error(`Unknown viewId: `+e)}};export{e as dotSource,t as svgSource};