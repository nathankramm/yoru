-- Evaluate Omarchy's Hyprland Lua config outside Hyprland and print every
-- bind it would make, one per line:
--
--   BIND<TAB>keys<TAB>description<TAB>dispatcher<TAB>file:line
--   UNBIND<TAB>keys<TAB><TAB><TAB>file:line
--
-- Usage:  lua tools/stock-binds.lua stock          # shipped defaults only
--         lua tools/stock-binds.lua full           # plus ~/.config/hypr/bindings.lua
--         lua tools/stock-binds.lua stock force    # pretend every optional app
--                                                  # is installed (voxtype, the
--                                                  # preinstalled web apps)
--
-- The real files are loaded through the real bootstrap and helpers, so the
-- `for workspace = 1, 10` loops, o.bind_toggle and the cmd_present guards all
-- evaluate exactly as they do in the compositor. `hl` is a recording stub:
-- any field or call yields another stub, and hl.bind / hl.unbind append to a
-- list. Only the description string and the key are trusted downstream; the
-- dispatcher column is a best-effort rendering for reading, not for parsing.

local mode, force = arg[1] or "stock", arg[2] == "force"
local omarchy = os.getenv("OMARCHY_PATH") or "/usr/share/omarchy"

local function describe(v, depth)
  depth = depth or 0
  if type(v) ~= "table" then return tostring(v) end
  local mt = getmetatable(v)
  if mt and mt.__proxy then
    local parts = {}
    for _, a in ipairs(rawget(v, "__args") or {}) do parts[#parts + 1] = describe(a, depth + 1) end
    return (rawget(v, "__path") or "?") .. "(" .. table.concat(parts, ", ") .. ")"
  end
  if depth > 2 then return "{...}" end
  local keys = {}
  for k in pairs(v) do keys[#keys + 1] = tostring(k) end
  table.sort(keys)
  local parts = {}
  for _, k in ipairs(keys) do parts[#parts + 1] = k .. "=" .. describe(v[k], depth + 1) end
  return "{" .. table.concat(parts, ", ") .. "}"
end

local function proxy(path)
  return setmetatable({ __path = path }, {
    __proxy = true,
    __index = function(t, k)
      -- helpers.lua's command_from() sniffs these fields on a built
      -- dispatcher to decide whether it is a launch table. It is not.
      if rawget(t, "__args") and (k == "omarchy" or k == "focus" or k == "launch"
                                  or k == "webapp" or k == "tui") then
        return nil
      end
      return proxy(path .. "." .. tostring(k))
    end,
    __call = function(_, ...)
      local r = proxy(path)
      r.__args = { ... }
      return r
    end,
  })
end

hl = proxy("hl")
local events = {}
-- The file:line that asked for the bind. Not a fixed stack depth: o.bind sits
-- between us and the caller, o.bind_toggle one deeper, and this function is
-- one deeper still. Walk up until the frame is outside helpers.lua and this
-- script, which is the config file that matters.
local function origin()
  for level = 2, 12 do
    local info = debug.getinfo(level, "Sl")
    if not info then break end
    local src = info.short_src
    if not src:match("helpers%.lua$") and not src:match("stock%-binds%.lua$") then
      return src .. ":" .. info.currentline
    end
  end
  return "?"
end
local function record(kind, keys, desc, dispatcher)
  events[#events + 1] = table.concat({ kind, keys, desc or "", dispatcher or "", origin() }, "\t")
end
rawset(hl, "bind", function(keys, dispatcher, opts)
  record("BIND", keys, opts and opts.description, describe(dispatcher))
end)
rawset(hl, "unbind", function(keys) record("UNBIND", keys, nil, nil) end)
rawset(hl, "get_active_window", function() return nil end)
for _, name in ipairs({ "on", "exec_cmd", "dispatch", "timer" }) do rawset(hl, name, function() end) end

dofile(omarchy .. "/default/hypr/bootstrap.lua")
require("default.hypr.helpers")
if force then
  o.cmd_present = function() return true end
  o.cmd_missing = function() return false end
  o.preinstalled_bindings_enabled = function() return true end
end
require("default.hypr.omarchy")
if mode == "full" then
  require("hypr.bindings")            -- ~/.config/hypr/bindings.lua
end
require("default.hypr.toggles")
for _, e in ipairs(events) do print(e) end
