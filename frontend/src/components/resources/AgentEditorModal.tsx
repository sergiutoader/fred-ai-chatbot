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
  Chip,
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

// OpenAPI slice (knowledge-flow)
import {
  Resource as KFResource,
  useListResourcesByKindKnowledgeFlowV1ResourcesGetQuery,
} from "../../slices/knowledgeFlow/knowledgeFlowOpenApi";

const mcpServerSchema = z.object({
  name: z.string().min(1, "Required"),
  url: z.string().url("Invalid URL"),
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
    timeout: typeof s?.timeout === "number" ? s!.timeout! : 600,
  }));

function extractServersFromMcpResource(r: KFResource) {
  const header =
    (r as any)?.metadata ??
    (() => {
      try {
        const content = (r as any)?.content as string | undefined;
        if (content && content.trimStart().startsWith("---")) {
          const end = content.indexOf("\n---", 3);
          if (end > 0) {
            const fm = content.slice(3, end);
            return (yaml.load(fm) as any) ?? {};
          }
        }
      } catch {}
      return {};
    })();

  const servers =
    header?.servers ||
    header?.mcpServers ||
    header?.mcp_servers ||
    [];

  if (Array.isArray(servers)) {
    return servers
      .map((s: any) => ({
        name: s?.name ?? (r as any)?.name ?? "MCP",
        url: s?.url ?? "",
        transport: (s?.transport as "sse" | "ws" | "http2") ?? "sse",
        timeout: typeof s?.timeout === "number" ? s.timeout : 600,
      }))
      .filter((s: any) => s.url);
  }

  if (servers && typeof servers === "object" && servers.url) {
    return [
      {
        name: servers.name ?? (r as any)?.name ?? "MCP",
        url: servers.url,
        transport: (servers.transport as "sse" | "ws" | "http2") ?? "sse",
        timeout: typeof servers.timeout === "number" ? servers.timeout : 600,
      },
    ];
  }

  return [];
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
    formState: { errors, isSubmitting },
  } = useForm<AgentFormData>({
    resolver: zodResolver(agentSchema),
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

  const { fields, append, remove, replace } = useFieldArray({
    control,
    name: "servers",
  });

  const serversCurrent = watch("servers") ?? [];

  const [headerText, setHeaderText] = useState<string>("");
  const [bodyText, setBodyText] = useState<string>("");
  const [headerError, setHeaderError] = useState<string | null>(null);
  const [suggesting, setSuggesting] = useState(false);

  // Load existing MCP resources
  const {
    data: existingMcp = [],
    isFetching: loadingMcp,
  } = useListResourcesByKindKnowledgeFlowV1ResourcesGetQuery(
    { kind: "mcp" },
    { skip: !isOpen }
  );

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
        type: (initial?.type as any) === "mcp" ? "mcp" : "mcp",
        labels: initial?.labels ?? [],
        basePrompt: initial?.basePrompt ?? "",
        servers: normalizeServers(initial?.servers),
      });
    }
  }, [
    isOpen,
    isDocMode,
    incomingDoc,
    initial?.name,
    initial?.nickname,
    initial?.description,
    initial?.role,
    initial?.icon,
    initial?.type,
    initial?.labels,
    initial?.basePrompt,
    initial?.servers,
    reset,
  ]);

  const handleAIHelp = async () => {
    if (!getSuggestion) return;
    try {
      setSuggesting(true);
      const suggestion = await getSuggestion();
      if (!suggestion) return;
      if (isDocMode) setBodyText(suggestion);
      else setValue("basePrompt", suggestion);
    } finally {
      setSuggesting(false);
    }
  };

  // Auto-merge selected MCP servers into form (no extra button)
  function addExistingMcpToServers(item: KFResource | null) {
    if (!item) return;
    const extracted = extractServersFromMcpResource(item);
    if (!extracted.length) return;

    const byUrl = new Set((serversCurrent || []).map((s) => s.url));
    const merged = [
      ...serversCurrent,
      ...extracted.filter((s) => s.url && !byUrl.has(s.url)),
    ];
    replace(merged);
  }

  const submitSimple = handleSubmit((data) => {
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
    onSave({
      name: data.name,
      description: data.description || undefined,
      labels: headerObj.labels,
      content,
    });
    onClose();
  });

  const onSubmitDoc = () => {
    let headerObj: Record<string, any>;
    try {
      headerObj = (yaml.load(headerText || "") as Record<string, any>) ?? {};
      setHeaderError(null);
    } catch (e: any) {
      setHeaderError(e?.message || "Invalid YAML");
      return;
    }
    if (!headerObj.kind) headerObj.kind = "agent";
    if (!headerObj.version) headerObj.version = "v1";

    const content = buildFrontMatter(headerObj, bodyText);
    onSave({
      content,
      name: headerObj.name,
      description: headerObj.description,
      labels: headerObj.labels,
    });
    onClose();
  };

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
        <form onSubmit={submitSimple}>
          <DialogContent>
            <Stack spacing={3} mt={1}>
              <Stack direction="row" spacing={2}>
                <TextField
                  label="Name"
                  fullWidth
                  {...register("name")}
                  error={!!errors.name}
                  helperText={errors.name?.message}
                />
                <TextField
                  label="Nickname"
                  fullWidth
                  {...register("nickname")}
                  error={!!errors.nickname}
                  helperText={errors.nickname?.message}
                />
              </Stack>

              <Stack direction="row" spacing={2}>
                <TextField
                  label="Description"
                  fullWidth
                  {...register("description")}
                  error={!!errors.description}
                  helperText={errors.description?.message}
                />
                <TextField
                  label="Role"
                  fullWidth
                  {...register("role")}
                  error={!!errors.role}
                  helperText={errors.role?.message}
                />
              </Stack>

              <TextField
                label="Labels (comma-separated)"
                fullWidth
                placeholder="sales, hr, beta"
                onChange={(e) =>
                  setValue(
                    "labels",
                    e.target.value
                      .split(",")
                      .map((s) => s.trim())
                      .filter(Boolean)
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
                <TextField
                  label="Agent Type"
                  fullWidth
                  select
                  defaultValue="mcp"
                  {...register("type")}
                  error={!!errors.type}
                  helperText={errors.type?.message}
                >
                  <MenuItem value="mcp">mcp</MenuItem>
                </TextField>
                <TextField
                  label="Icon"
                  fullWidth
                  {...register("icon")}
                  error={!!errors.icon}
                  helperText={errors.icon?.message}
                />
              </Stack>

              {/* Pick existing MCP → auto-fill servers */}
              <Stack spacing={1}>
                <Typography variant="subtitle1">Use existing MCP server</Typography>
                <Autocomplete
                  options={existingMcp as KFResource[]}
                  getOptionLabel={(o) => (o as any)?.name || "MCP"}
                  loading={loadingMcp}
                  onChange={(_, v) => addExistingMcpToServers(v as KFResource | null)}
                  sx={{ flex: 1, minWidth: 280 }}
                  renderInput={(params) => (
                    <TextField
                      {...params}
                      label="Existing MCP"
                      placeholder={loadingMcp ? "Loading..." : "Select an MCP resource"}
                    />
                  )}
                  renderOption={(props, option) => {
                    const servers = extractServersFromMcpResource(option as KFResource);
                    const subtitle =
                      servers.length
                        ? servers.map((s) => s.url).slice(0, 2).join(" · ")
                        : "No server info";
                    return (
                      <li {...props} key={String((option as any).id)}>
                        <Stack>
                          <Typography variant="body2" fontWeight={600}>
                            {(option as any).name || "MCP"}
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            {subtitle}
                          </Typography>
                        </Stack>
                      </li>
                    );
                  }}
                />

                {!!serversCurrent.length && (
                  <Stack direction="row" spacing={1} flexWrap="wrap">
                    {serversCurrent.map((s, idx) => (
                      <Chip
                        key={`${s.url}-${idx}`}
                        label={`${s.name || "MCP"} • ${s.transport} • ${s.timeout}s`}
                        onDelete={() => remove(idx)}
                        variant="outlined"
                        sx={{ mr: 0.5, mb: 0.5 }}
                      />
                    ))}
                  </Stack>
                )}
              </Stack>

              {/* Manual servers editor (optional) */}
              <Stack spacing={1}>
                <Typography variant="subtitle1">MCP Servers</Typography>
                {fields.map((field, index) => (
                  <Stack key={field.id} direction="row" spacing={1} alignItems="center">
                    <TextField
                      label="Name"
                      sx={{ flex: 1 }}
                      {...register(`servers.${index}.name` as const)}
                      error={!!errors.servers?.[index]?.name}
                      helperText={errors.servers?.[index]?.name?.message}
                    />
                    <TextField
                      label="URL"
                      sx={{ flex: 2 }}
                      {...register(`servers.${index}.url` as const)}
                      error={!!errors.servers?.[index]?.url}
                      helperText={errors.servers?.[index]?.url?.message}
                    />
                    <Controller
                      control={control}
                      name={`servers.${index}.transport` as const}
                      render={({ field }) => (
                        <TextField label="Transport" select sx={{ width: 140 }} {...field}>
                          <MenuItem value="sse">sse</MenuItem>
                          <MenuItem value="ws">ws</MenuItem>
                          <MenuItem value="http2">http2</MenuItem>
                        </TextField>
                      )}
                    />
                    <Controller
                      control={control}
                      name={`servers.${index}.timeout` as const}
                      render={({ field }) => (
                        <TextField
                          label="Timeout"
                          type="number"
                          sx={{ width: 120 }}
                          inputProps={{ min: 1, max: 3600 }}
                          {...field}
                        />
                      )}
                    />
                    <IconButton aria-label="delete" onClick={() => remove(index)}>
                      <DeleteIcon />
                    </IconButton>
                  </Stack>
                ))}
                <Button
                  startIcon={<AddIcon />}
                  variant="outlined"
                  onClick={() =>
                    append({ name: "", url: "", transport: "sse", timeout: 600 })
                  }
                  sx={{ alignSelf: "flex-start" }}
                >
                  Add a MCP server
                </Button>
              </Stack>
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
            <Button type="submit" variant="contained" disabled={isSubmitting}>
              Save
            </Button>
          </DialogActions>
        </form>
      )}
    </Dialog>
  );
};
