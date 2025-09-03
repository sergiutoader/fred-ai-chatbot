// McpServerEditorModal.tsx
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
} from "@mui/material";
import * as React from "react";
import { useEffect, useMemo, useState } from "react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";
import { zodResolver } from "@hookform/resolvers/zod";
import yaml from "js-yaml";
import { buildFrontMatter, looksLikeYamlDoc, splitFrontMatter } from "./resourceYamlUtils";

const serverSchema = z.object({
  name: z.string().min(1, "Name is required"),
  description: z.string().optional(),
  url: z.string().url("Invalid URL"),
  transport: z.enum(["sse", "ws", "http2"]),
  timeout: z.number().int().min(1).max(3600),
});

type ServerFormData = z.infer<typeof serverSchema>;

type ResourceCreateLike = {
  name?: string;
  description?: string;
  labels?: string[];
  content: string;
};

interface McpEditorModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: (payload: ResourceCreateLike) => void;
  initial?: Partial<{
    name: string;
    description?: string;
    url?: string;
    transport?: "sse" | "ws" | "http2";
    timeout?: number;
    yaml?: string;
  }>;
}

export const McpEditorModal: React.FC<McpEditorModalProps> = ({
  isOpen,
  onClose,
  onSave,
  initial,
}) => {
  const incomingDoc = useMemo(() => (initial as any)?.yaml ?? "", [initial]);
  const isDocMode = useMemo(() => looksLikeYamlDoc(incomingDoc), [incomingDoc]);

  const {
    control,
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<ServerFormData>({
    resolver: zodResolver(serverSchema),
    defaultValues: {
      name: "",
      description: "",
      url: "",
      transport: "sse",
      timeout: 600,
    },
  });

  const [headerText, setHeaderText] = useState<string>("");
  const [bodyText, setBodyText] = useState<string>("");
  const [headerError, setHeaderError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen) return;

    if (isDocMode) {
      const { header, body } = splitFrontMatter(incomingDoc);
      setHeaderText(yaml.dump(header).trim());
      setBodyText(body || "");
    } else {
      reset({
        name: initial?.name ?? "",
        description: initial?.description ?? "",
        url: initial?.url ?? "",
        transport: initial?.transport ?? "sse",
        timeout: initial?.timeout ?? 600,
      });
    }
  }, [
    isOpen,
    isDocMode,
    incomingDoc,
    initial?.name,
    initial?.description,
    initial?.url,
    initial?.transport,
    initial?.timeout,
    reset,
  ]);

  const onSubmitSimple = (data: ServerFormData) => {
    const server = {
      name: data.name,
      url: data.url,
      transport: data.transport,
      timeout: data.timeout,
    };

    const headerObj: Record<string, any> = {
      kind: "mcp",
      version: "v1",
      name: data.name,
      description: data.description || undefined,
      // both keys for compatibility
      servers: [server],
      mcpServers: [server],
    };

    // non-empty body to satisfy backend guard
    const content = buildFrontMatter(headerObj, "# MCP server");
    onSave({
      name: data.name,
      description: data.description || undefined,
      content,
    });
    onClose();
  };

  const onSubmitDoc = () => {
    let headerObj: Record<string, any>;
    try {
      headerObj = (yaml.load(headerText || "") as Record<string, any>) ?? {};
      setHeaderError(null);
    } catch (e: any) {
      setHeaderError(e?.message || "Invalid YAML");
      return;
    }

    // normalize kind/version
    if (!headerObj.kind || String(headerObj.kind).toLowerCase() !== "mcp") {
      headerObj.kind = "mcp";
    }
    if (!headerObj.version) headerObj.version = "v1";

    // ensure servers array shape if user typed single fields
    const maybeUrl = headerObj.url;
    const maybeTransport = headerObj.transport;
    const maybeTimeout = headerObj.timeout;
    if (!headerObj.servers && !headerObj.mcpServers) {
      if (maybeUrl) {
        const server = {
          name: headerObj.name ?? "MCP",
          url: maybeUrl,
          transport: (maybeTransport as "sse" | "ws" | "http2") ?? "sse",
          timeout: typeof maybeTimeout === "number" ? maybeTimeout : 600,
        };
        headerObj.servers = [server];
        headerObj.mcpServers = [server];
      }
    }

    const safeBody = (bodyText && bodyText.trim().length > 0) ? bodyText : "# MCP server";
    const content = buildFrontMatter(headerObj, safeBody);

    onSave({
      content,
      name: headerObj.name,
      description: headerObj.description,
      labels: headerObj.labels,
    });
    onClose();
  };

  return (
    <Dialog open={isOpen} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>{initial ? "Edit MCP Server" : "Create MCP Server"}</DialogTitle>

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
                helperText={headerError || "Edit server metadata (name, url/servers, transport, timeout, etc.)"}
              />
              <TextField
                label="Body (optional)"
                fullWidth
                multiline
                minRows={6}
                value={bodyText}
                onChange={(e) => setBodyText(e.target.value)}
                helperText="Optional body."
              />
            </Stack>
          </DialogContent>
          <DialogActions>
            <Button onClick={onClose} variant="outlined">Cancel</Button>
            <Button
              onClick={onSubmitDoc}
              variant="contained"
              startIcon={<CircularProgress size={16} sx={{ display: "none" }} />}
            >
              Save
            </Button>
          </DialogActions>
        </>
      ) : (
        <form onSubmit={handleSubmit(onSubmitSimple)}>
          <DialogContent>
            <Stack spacing={3} mt={1}>
              <TextField
                label="Name"
                fullWidth
                {...register("name")}
                error={!!errors.name}
                helperText={errors.name?.message}
              />
              <TextField
                label="Description (optional)"
                fullWidth
                {...register("description")}
                error={!!errors.description}
                helperText={errors.description?.message}
              />
              <TextField
                label="URL"
                fullWidth
                {...register("url")}
                error={!!errors.url}
                helperText={errors.url?.message}
              />
              <Stack direction="row" spacing={2}>
                <Controller
                  control={control}
                  name="transport"
                  render={({ field }) => (
                    <TextField label="Transport" select fullWidth {...field}>
                      <MenuItem value="sse">sse</MenuItem>
                      <MenuItem value="ws">ws</MenuItem>
                      <MenuItem value="http2">http2</MenuItem>
                    </TextField>
                  )}
                />
                <Controller
                  control={control}
                  name="timeout"
                  render={({ field }) => (
                    <TextField
                      label="Timeout (s)"
                      type="number"
                      fullWidth
                      inputProps={{ min: 1, max: 3600 }}
                      {...field}
                      error={!!errors.timeout}
                      helperText={errors.timeout?.message}
                    />
                  )}
                />
              </Stack>
            </Stack>
          </DialogContent>
          <DialogActions>
            <Button onClick={onClose} variant="outlined">Cancel</Button>
            <Button type="submit" variant="contained" disabled={isSubmitting}>
              Save
            </Button>
          </DialogActions>
        </form>
      )}
    </Dialog>
  );
};
