// AgentEditorModal.tsx
import {
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  TextField,
  Typography,
  IconButton,
} from "@mui/material";
import DeleteIcon from "@mui/icons-material/Delete";
import AddIcon from "@mui/icons-material/Add";
import * as React from "react";
import { useEffect, useMemo, useState } from "react";
import { Controller, useFieldArray, useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import yaml from "js-yaml";
import Autocomplete from "@mui/material/Autocomplete";

import {
  buildFrontMatter,
  looksLikeYamlDoc,
  splitFrontMatter,
} from "./resourceYamlUtils";

import {
  Resource as KFResource,
  useListResourcesByKindKnowledgeFlowV1ResourcesGetQuery,
  useLazyGetResourceKnowledgeFlowV1ResourcesIdGetQuery,
} from "../../slices/knowledgeFlow/knowledgeFlowOpenApi";

const mcpServerSchema = z.object({
  name: z.string().min(1, "Required"),
  url: z.string().min(1, "URL is required"),
  transport: z.enum(["sse", "ws", "http2"]),
  timeout: z.number().int().min(1).max(3600),
});

const agentSchema = z.object({
  name: z.string().min(1, "Name is required"),
  basePrompt: z.string().min(1, "Base Prompt is required"),
  type: z.enum(["mcp"]),
  servers: z.array(mcpServerSchema).min(1, "At least one MCP server is required"),
  description: z.string().optional(),
  nickname: z.string().optional(),
  role: z.string().optional(),
  icon: z.string().optional(),
  labels: z.array(z.string()).optional(),
});

type AgentFormData = z.infer<typeof agentSchema>;

type ResourceCreateLike = {
  name?: string;
  description?: string;
  labels?: string[];
  content: string;
};

interface AgentEditorModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (payload: ResourceCreateLike) => void;
  initial?: Partial<{
    name: string;
    nickname?: string;
    description?: string;
    role?: string;
    icon?: string;
    type?: string;
    labels?: string[];
    basePrompt?: string;
    servers?: Partial<z.infer<typeof mcpServerSchema>>[];
    yaml?: string;
  }>;
  getSuggestion?: () => Promise<string>;
}

const normalizeServers = (arr?: Partial<z.infer<typeof mcpServerSchema>>[]) =>
  (arr ?? []).map((s) => ({
    name: s?.name ?? "",
    url: s?.url ?? "",
    transport: (s?.transport as "sse" | "ws" | "http2") ?? "sse",
    timeout: Number.isFinite(s?.timeout) ? (s?.timeout as number) : 600,
  }));

// ---- Helpers de parsing avec logs
function parseHeaderFromContent(content: string): any {
  const preview = content.slice(0, 200).replace(/\n/g, "\\n");
  console.debug("[AgentEditor][parse] content preview:", preview);

  const trimmed = content.trimStart();

  // 1) Front-matter en tête: --- ... \n---
  if (trimmed.startsWith("---")) {
    const end = trimmed.indexOf("\n---", 3);
    console.debug("[AgentEditor][parse] starts with '---', end idx:", end);
    if (end > 0) {
      try {
        const fm = trimmed.slice(3, end);
        const head = (yaml.load(fm) as any) ?? {};
        console.debug("[AgentEditor][parse] front-matter keys:", Object.keys(head || {}));
        if (head && typeof head === "object") return head;
      } catch (e) {
        console.warn("[AgentEditor][parse] front-matter load failed:", e);
      }
    }
  }

  // 2) Single doc
  try {
    const obj = yaml.load(content);
    if (obj && typeof obj === "object") {
      console.debug("[AgentEditor][parse] yaml.load ok, keys:", Object.keys(obj as any));
      return obj as any;
    }
  } catch (e: any) {
    console.warn("[AgentEditor][parse] yaml.load failed, try loadAll. err:", e?.message);
    // 3) Multi-doc: on prend celui qui a servers/mcpServers
    try {
      const docs: any[] = [];
      yaml.loadAll(content, (doc) => docs.push(doc));
      console.debug("[AgentEditor][parse] yaml.loadAll docs:", docs.length);
      const preferred =
        docs.find(
          (d) =>
            d &&
            typeof d === "object" &&
            (Array.isArray((d as any).servers) ||
              Array.isArray((d as any).mcpServers) ||
              Array.isArray((d as any).mcp_servers))
        ) || docs[0];
      if (preferred && typeof preferred === "object") {
        console.debug("[AgentEditor][parse] picked doc keys:", Object.keys(preferred));
        return preferred;
      }
    } catch (e2) {
      console.warn("[AgentEditor][parse] yaml.loadAll failed:", e2);
    }
  }

  console.debug("[AgentEditor][parse] no header parsed, return {}");
  return {};
}

function extractServersFromMcpResource(r: KFResource) {
  const meta = (r as any)?.metadata;
  if (meta && typeof meta === "object") {
    console.debug("[AgentEditor][extract] using metadata keys:", Object.keys(meta || {}));
  }

  let header: any = meta && typeof meta === "object" ? meta : {};
  if (!Object.keys(header).length) {
    const content = (r as any)?.content as string | undefined;
    if (typeof content === "string" && content.trim().length) {
      header = parseHeaderFromContent(content);
    } else {
      console.debug("[AgentEditor][extract] no metadata/content on resource");
    }
  }

  const pickServersArray = (h: any): any[] => {
    if (!h || typeof h !== "object") return [];
    const candidates = [
      h.servers,
      h.mcpServers,
      h.mcp_servers,
      h.endpoints,
      h.mcp_endpoints,
    ].find((v) => Array.isArray(v)) as any[] | undefined;

    console.debug(
      "[AgentEditor][extract] servers array present:",
      !!candidates,
      "header keys:",
      Object.keys(h || {})
    );

    if (candidates) return candidates;

    const single =
      [h.server, h.mcpServer, h.mcp_server, h.connection, h.endpoint, h.mcp_endpoint, h].find(
        (v) => v && typeof v === "object" && ("url" in v || "baseUrl" in v)
      ) || null;

    console.debug("[AgentEditor][extract] single server present:", !!single);
    return single ? [single] : [];
  };

  const toServer = (s: any): any => {
    const resolved = {
      name: s?.name ?? (r as any)?.name ?? "MCP",
      url: (s?.url ?? s?.baseUrl ?? "").toString(),
      transport: (s?.transport as "sse" | "ws" | "http2") ?? "sse",
      timeout: typeof s?.timeout === "number" ? s.timeout : 600,
    };
    console.debug("[AgentEditor][extract] toServer mapped:", resolved);
    return resolved;
  };

  const serversRaw = pickServersArray(header);
  console.debug("[AgentEditor][extract] serversRaw length:", serversRaw.length, "sample[0]:", serversRaw[0]);
  const out = serversRaw.map(toServer).filter((s) => !!s.url);
  console.debug("[AgentEditor][extract] extracted servers:", out);
  return out;
}

export const AgentEditorModal: React.FC<AgentEditorModalProps> = ({
  isOpen,
  onClose,
  onSave,
  initial,
  getSuggestion,
}) => {
  const incomingDoc = useMemo(() => (initial as any)?.yaml ?? "", [initial]);
  const isDocMode = useMemo(() => looksLikeYamlDoc(incomingDoc), [incomingDoc]);

  const {
    control,
    register,
    handleSubmit,
    setValue,
    reset,
    watch,
    trigger,
    formState: { errors, isSubmitting },
  } = useForm<AgentFormData>({
    resolver: zodResolver(agentSchema),
    mode: "onChange",
    reValidateMode: "onChange",
    defaultValues: {
      name: "",
      basePrompt: "",
      type: "mcp",
      servers: [],
      nickname: "",
      description: "",
      role: "",
      icon: "Robot",
      labels: [],
    },
  });

  const { fields, append, remove } = useFieldArray({ control, name: "servers" });
  const serversCurrent = watch("servers") ?? [];

  const [headerText, setHeaderText] = useState<string>("");
  const [bodyText, setBodyText] = useState<string>("");
  const [headerError, setHeaderError] = useState<string | null>(null);
  const [suggesting, setSuggesting] = useState(false);
  const [selectedMcp, setSelectedMcp] = useState<KFResource | null>(null);

  const {
    data: existingMcp = [],
    isFetching: loadingMcp,
  } = useListResourcesByKindKnowledgeFlowV1ResourcesGetQuery(
    { kind: "mcp" },
    { skip: !isOpen }
  );

  const [getResourceById, { isFetching: loadingOne }] =
    useLazyGetResourceKnowledgeFlowV1ResourcesIdGetQuery();

  useEffect(() => {
    if (!isOpen) return;
    if (isDocMode) {
      const { header, body } = splitFrontMatter(incomingDoc);
      setHeaderText(yaml.dump(header).trim());
      setBodyText(body);
    } else {
      reset({
        name: initial?.name ?? "",
        nickname: initial?.nickname ?? "",
        description: initial?.description ?? "",
        role: initial?.role ?? "",
        icon: initial?.icon ?? "Robot",
        type: "mcp",
        labels: initial?.labels ?? [],
        basePrompt: initial?.basePrompt ?? "",
        servers: normalizeServers(initial?.servers),
      });
    }
  }, [isOpen, isDocMode, incomingDoc, initial?.name, initial?.nickname, initial?.description, initial?.role, initial?.icon, initial?.labels, initial?.basePrompt, initial?.servers, reset]);

  const handleAIHelp = async () => {
    if (!getSuggestion) return;
    try {
      setSuggesting(true);
      const suggestion = await getSuggestion();
      if (!suggestion) return;
      if (isDocMode) setBodyText(suggestion);
      else setValue("basePrompt", suggestion, { shouldDirty: true, shouldValidate: true });
    } finally {
      setSuggesting(false);
    }
  };

  const addExistingMcpToServers = async (item: KFResource | null) => {
    setSelectedMcp(item);
    console.log("[AgentEditor] onSelect existing MCP:", item);
    if (!item) return;

    let extracted = extractServersFromMcpResource(item);

    if (!extracted.length && (item as any)?.id) {
      try {
        console.log("[AgentEditor] fetching full resource by id:", (item as any).id);
        const full = await getResourceById({ id: (item as any).id }).unwrap();
        console.log("[AgentEditor] full resource fetched:", full);
        if (full && (full as any).content) {
          const content: string = (full as any).content;
          console.debug("[AgentEditor] full.content preview:", content.slice(0, 200).replace(/\n/g, "\\n"));
        }
        if (full) extracted = extractServersFromMcpResource(full as KFResource);
      } catch (e) {
        console.warn("[AgentEditor] GET resource by id failed:", e);
      }
    }

    console.log("[AgentEditor] extracted servers to append:", extracted);

    if (extracted.length) {
      const byUrl = new Set((serversCurrent || []).map((s) => (s.url || "").trim()));
      extracted.forEach((srv, idx) => {
        const url = (srv.url || "").trim();
        const name = srv.name || ((item as any)?.name as string) || "MCP";
        const transport = (srv.transport as "sse" | "ws" | "http2") ?? "sse";
        const timeout = Number.isFinite(srv.timeout) ? (srv.timeout as number) : 600;

        console.debug("[AgentEditor] append server:", { idx, name, url, transport, timeout });

        if (url && byUrl.has(url)) {
          console.debug("[AgentEditor] skip duplicate url:", url);
          return;
        }
        append({ name, url, transport, timeout });
        if (url) byUrl.add(url);
      });
    } else {
      const fallbackName = ((item as any)?.name as string) || "MCP";
      console.warn("[AgentEditor] no servers extracted; append empty row with name:", fallbackName);
      append({ name: fallbackName, url: "", transport: "sse", timeout: 600 });
    }

    queueMicrotask(() => { void trigger("servers"); });
  };

  const onSubmitSimple = (data: AgentFormData) => {
    console.debug("[AgentEditor] onSubmitSimple payload:", data);
    const headerObj: Record<string, any> = {
      kind: "agent",
      version: "v1",
      name: data.name,
      nickname: data.nickname || undefined,
      description: data.description || undefined,
      role: data.role || undefined,
      icon: data.icon || undefined,
      type: data.type,
      labels: data.labels && data.labels.length ? data.labels : undefined,
      mcpServers: data.servers ?? [],
    };

    const content = buildFrontMatter(headerObj, (data.basePrompt || "").trim());
    console.debug("[AgentEditor] built content preview:", content.slice(0, 200).replace(/\n/g, "\\n"));
    onSave({ name: data.name, description: data.description || undefined, labels: headerObj.labels, content });
    onClose();
  };

  const onSubmitDoc = () => {
    try {
      const headerObj = (yaml.load(headerText || "") as Record<string, any>) ?? {};
      const content = buildFrontMatter({ kind: headerObj.kind || "agent", version: headerObj.version || "v1", ...headerObj }, bodyText);
      console.debug("[AgentEditor] onSubmitDoc content preview:", content.slice(0, 200).replace(/\n/g, "\\n"));
      onSave({ content, name: (headerObj as any).name, description: (headerObj as any).description, labels: (headerObj as any).labels });
      onClose();
    } catch (e: any) {
      setHeaderError(e?.message || "Invalid YAML");
      console.warn("[AgentEditor] header YAML parse error:", e);
    }
  };

  const serversArrayError =
    (errors?.servers as any)?.message || (errors?.servers as any)?.root?.message || "";

  return (
    <Dialog open={isOpen} onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>{initial ? "Edit Agent" : "Create Agent"}</DialogTitle>

      {isDocMode ? (
        <>
          <DialogContent>
            <Stack spacing={3} mt={1}>
              <TextField
                label="Header (YAML)"
                fullWidth
                multiline
                minRows={10}
                value={headerText}
                onChange={(e) => setHeaderText(e.target.value)}
                error={!!headerError}
                helperText={headerError || "Edit agent metadata (name, nickname, role, labels, mcpServers, etc.)"}
              />
              <TextField
                label="Base Prompt"
                fullWidth
                multiline
                minRows={14}
                value={bodyText}
                onChange={(e) => setBodyText(e.target.value)}
                helperText="Use {placeholders} to define inputs."
              />
            </Stack>
          </DialogContent>
          <DialogActions>
            <Button onClick={onClose} variant="outlined">Cancel</Button>
            <Button
              onClick={handleAIHelp}
              variant="text"
              disabled={!getSuggestion || suggesting}
              startIcon={suggesting ? <CircularProgress size={16} /> : undefined}
            >
              Get Help from AI
            </Button>
            <Button onClick={onSubmitDoc} variant="contained">Save</Button>
          </DialogActions>
        </>
      ) : (
        <form onSubmit={handleSubmit(onSubmitSimple)}>
          <DialogContent>
            <Stack spacing={3} mt={1}>
              <Stack direction="row" spacing={2}>
                <TextField label="Name" fullWidth {...register("name")} error={!!errors.name} helperText={errors.name?.message} />
                <TextField label="Nickname" fullWidth {...register("nickname")} error={!!errors.nickname} helperText={errors.nickname?.message} />
              </Stack>

              <Stack direction="row" spacing={2}>
                <TextField label="Description" fullWidth {...register("description")} error={!!errors.description} helperText={errors.description?.message} />
                <TextField label="Role" fullWidth {...register("role")} error={!!errors.role} helperText={errors.role?.message} />
              </Stack>

              <TextField
                label="Labels (comma-separated)"
                fullWidth
                placeholder="sales, hr, beta"
                defaultValue={(initial?.labels ?? []).join(", ")}
                onChange={(e) =>
                  setValue(
                    "labels",
                    e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                    { shouldDirty: true, shouldValidate: false }
                  )
                }
              />

              <TextField
                label="Base Prompt"
                fullWidth
                multiline
                minRows={14}
                {...register("basePrompt")}
                error={!!errors.basePrompt}
                helperText={errors.basePrompt?.message || "Use {placeholders} to define inputs."}
              />

              <Stack direction="row" spacing={2}>
                <TextField label="Agent Type" fullWidth select defaultValue="mcp" {...register("type")} error={!!errors.type} helperText={errors.type?.message}>
                  <MenuItem value="mcp">mcp</MenuItem>
                </TextField>
                <TextField label="Icon" fullWidth {...register("icon")} error={!!errors.icon} helperText={errors.icon?.message} />
              </Stack>

              <Stack spacing={1}>
                <Typography variant="subtitle1">Use existing MCP server</Typography>
                <Autocomplete
                  options={existingMcp as KFResource[]}
                  value={selectedMcp}
                  isOptionEqualToValue={(a, b) => (a as any)?.id === (b as any)?.id}
                  getOptionLabel={(o) => (o as any)?.name || "MCP"}
                  loading={loadingMcp || loadingOne}
                  onChange={(_, v) => { void addExistingMcpToServers(v as KFResource | null); }}
                  sx={{ flex: 1, minWidth: 280 }}
                  renderInput={(params) => (
                    <TextField
                      {...params}
                      label="Existing MCP"
                      placeholder={loadingMcp ? "Loading..." : "Select an MCP resource"}
                      helperText="Selecting one will add pre-filled rows below."
                    />
                  )}
                  renderOption={(props, option) => {
                    const servers = extractServersFromMcpResource(option as KFResource);
                    const subtitle = servers.length ? servers.map((s) => s.url).slice(0, 2).join(" · ") : "No server info";
                    return (
                      <li {...props} key={String((option as any).id)}>
                        <Stack>
                          <Typography variant="body2" fontWeight={600}>{(option as any).name || "MCP"}</Typography>
                          <Typography variant="caption" color="text.secondary">{subtitle}</Typography>
                        </Stack>
                      </li>
                    );
                  }}
                />
                {serversArrayError ? <Typography variant="caption" color="error">{String(serversArrayError)}</Typography> : null}
              </Stack>

              <Stack spacing={1}>
                <Typography variant="subtitle1">MCP Servers</Typography>
                {fields.map((field, index) => (
                  <Stack key={field.id} direction="row" spacing={1} alignItems="center">
                    <TextField label="Name" sx={{ flex: 1 }} {...register(`servers.${index}.name` as const)} error={!!errors.servers?.[index]?.name} helperText={errors.servers?.[index]?.name?.message} onBlur={() => { void trigger("servers"); }} />
                    <TextField label="URL" sx={{ flex: 2 }} {...register(`servers.${index}.url` as const)} error={!!errors.servers?.[index]?.url} helperText={errors.servers?.[index]?.url?.message} onBlur={() => { void trigger("servers"); }} />
                    <Controller control={control} name={`servers.${index}.transport` as const} render={({ field }) => (
                      <TextField label="Transport" select sx={{ width: 140 }} {...field}>
                        <MenuItem value="sse">sse</MenuItem>
                        <MenuItem value="ws">ws</MenuItem>
                        <MenuItem value="http2">http2</MenuItem>
                      </TextField>
                    )} />
                    <Controller control={control} name={`servers.${index}.timeout` as const} render={({ field }) => (
                      <TextField label="Timeout" type="number" sx={{ width: 120 }} inputProps={{ min: 1, max: 3600 }} {...field} onBlur={() => { void trigger("servers"); }} />
                    )} />
                    <IconButton aria-label="delete" onClick={() => { remove(index); queueMicrotask(() => { void trigger("servers"); }); }}>
                      <DeleteIcon />
                    </IconButton>
                  </Stack>
                ))}

                <Button
                  startIcon={<AddIcon />}
                  variant="outlined"
                  onClick={() => { console.debug("[AgentEditor] manual add server row"); append({ name: "", url: "", transport: "sse", timeout: 600 }); queueMicrotask(() => { void trigger("servers"); }); }}
                  sx={{ alignSelf: "flex-start" }}
                >
                  Add a MCP server
                </Button>
              </Stack>
            </Stack>
          </DialogContent>
          <DialogActions>
            <Button onClick={onClose} variant="outlined">Cancel</Button>
            <Button onClick={handleAIHelp} variant="text" disabled={!getSuggestion || suggesting} startIcon={suggesting ? <CircularProgress size={16} /> : undefined}>
              Get Help from AI
            </Button>
            <Button type="submit" variant="contained" disabled={isSubmitting}>Save</Button>
          </DialogActions>
        </form>
      )}
    </Dialog>
  );
};
