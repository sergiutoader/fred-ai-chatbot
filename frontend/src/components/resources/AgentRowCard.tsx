// Copyright Thales 2025
// Licensed under the Apache License, Version 2.0

import {
  Avatar,
  Box,
  Chip,
  IconButton,
  Tooltip,
  Typography,
  alpha,
} from "@mui/material";
import KeyboardArrowRightIcon from "@mui/icons-material/KeyboardArrowRight";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import StarBorderIcon from "@mui/icons-material/StarBorder";
import LanIcon from "@mui/icons-material/Lan";
import yaml from "js-yaml";
import { Resource } from "../../slices/knowledgeFlow/knowledgeFlowOpenApi";
import { splitFrontMatter } from "./resourceYamlUtils";

function safeFrontMatterFromContent(content?: unknown): Record<string, any> {
  if (typeof content !== "string") return {};
  const text = content.trim();
  if (!text) return {};
  // YAML front-matter
  if (text.startsWith("---")) {
    try {
      const { header } = splitFrontMatter(text);
      return (header as Record<string, any>) ?? {};
    } catch {
      // ignore
    }
  }
  // Pure YAML (no front-matter fences)
  if (/^[\w-]+:/.test(text)) {
    try {
      const obj = yaml.load(text);
      if (obj && typeof obj === "object") return obj as Record<string, any>;
    } catch {
      // ignore
    }
  }
  // JSON
  if (text.startsWith("{")) {
    try {
      const obj = JSON.parse(text);
      if (obj && typeof obj === "object") return obj as Record<string, any>;
    } catch {
      // ignore
    }
  }
  return {};
}

function readHeader(r: Resource): Record<string, any> {
  // common places
  const direct =
    (r as any)?.header ??
    (r as any)?.metadata ??
    (r as any)?.front_matter ??
    (r as any)?.config ??
    undefined;

  if (direct && typeof direct === "object") return direct as Record<string, any>;
  // fallback parse from content
  return safeFrontMatterFromContent((r as any)?.content);
}

export function isAgentResource(r: Resource): boolean {
  const k =
    (r as any)?.kind ??
    (r as any)?.metadata?.kind ??
    readHeader(r)?.kind;
  return String(k || "").toLowerCase() === "agent";
}

function getAgentTitle(r: Resource) {
  const h = readHeader(r);
  return (
    (r as any)?.name ||
    (r as any)?.metadata?.name ||
    h?.name ||
    (r as any)?.display_name ||
    `Agent`
  );
}

function getAgentSubtitle(r: Resource) {
  const h = readHeader(r);
  return (
    (r as any)?.role ||
    (r as any)?.subtitle ||
    (r as any)?.metadata?.role ||
    h?.role ||
    (r as any)?.description ||
    ""
  );
}

function getAgentLabels(r: Resource): string[] {
  const h = readHeader(r);
  const labels =
    (r as any)?.labels ||
    (r as any)?.metadata?.labels ||
    h?.labels ||
    [];
  return Array.isArray(labels) ? labels.slice(0, 3) : [];
}

/** Ultra-tolerant MCP server extractor. */
function getAgentMcpServers(r: Resource): Array<{ name?: string; url?: string }> {
  // Try many shapes
  const rootCandidates = [
    (r as any)?.mcpServers,
    (r as any)?.mcp_servers,
    (r as any)?.servers, // some UIs stick it at root
  ];
  for (const c of rootCandidates) if (Array.isArray(c)) return c;

  const h = readHeader(r);
  const headerCandidates = [
    h?.mcpServers,
    h?.mcp_servers,
    h?.servers,
    h?.mcp?.servers,
    h?.agent?.mcpServers,
    h?.config?.mcpServers,
  ];
  for (const c of headerCandidates) if (Array.isArray(c)) return c;

  return [];
}

function agentInitial(name: string) {
  return (name?.trim?.()[0] || "A").toUpperCase();
}

export function AgentRowCard({
  resource,
  onPreview,
  onEdit,
  onRemoveFromLibrary,
}: {
  resource: Resource;
  onPreview?: (p: Resource) => void;
  onEdit?: (p: Resource) => void;
  onRemoveFromLibrary?: (p: Resource) => void;
}) {
  const title = getAgentTitle(resource);
  const subtitle = getAgentSubtitle(resource);
  const labels = getAgentLabels(resource);
  const mcpServers = getAgentMcpServers(resource);
  const mcpCount = mcpServers.length;

  return (
    <Box
      sx={(theme) => ({
        flex: 1,
        display: "flex",
        alignItems: "center",
        gap: 1.25,
        p: 1,
        borderRadius: 1.5,
        border: `1px solid ${alpha(theme.palette.divider, 0.8)}`,
        bgcolor: theme.palette.background.paper,
        boxShadow: `0 1px 2px ${alpha(theme.palette.common.black, 0.06)}`,
        minHeight: 64,
        "&:hover": {
          borderColor: theme.palette.primary.light,
          boxShadow: `0 2px 6px ${alpha(theme.palette.primary.main, 0.12)}`,
        },
      })}
    >
      <Avatar sx={{ width: 28, height: 28, fontSize: 14 }}>
        {agentInitial(title)}
      </Avatar>

      <Box sx={{ minWidth: 0, flex: 1, display: "flex", flexDirection: "column" }}>
        <Typography
          variant="subtitle1"
          sx={{ lineHeight: 1.2, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
          title={title}
        >
          {title}
        </Typography>
        {subtitle ? (
          <Typography
            variant="body2"
            color="text.secondary"
            sx={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
            title={subtitle}
          >
            {subtitle}
          </Typography>
        ) : null}

        {labels?.length ? (
          <Box sx={{ mt: 0.5, display: "flex", gap: 0.5, flexWrap: "wrap" }}>
            {labels.map((l) => (
              <Chip key={l} label={l} size="small" variant="outlined" />
            ))}
          </Box>
        ) : null}
      </Box>

      <Box sx={{ display: "flex", alignItems: "center", gap: 0.5 }}>
        <Tooltip
          title={
            mcpCount
              ? `MCP servers: ${mcpServers.map((s) => s?.name || s?.url).join(", ")}`
              : "No MCP server linked"
          }
        >
          <Chip
            size="small"
            icon={<LanIcon fontSize="small" />}
            label={mcpCount ? `MCP ${mcpCount}` : "MCP"}
            variant={mcpCount ? "filled" : "outlined"}
            color={mcpCount ? "success" : "default"}
          />
        </Tooltip>

        {onPreview ? (
          <Tooltip title="Preview">
            <IconButton size="small" onClick={(e) => { e.stopPropagation(); onPreview(resource); }}>
              <KeyboardArrowRightIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        ) : null}
        {onEdit ? (
          <Tooltip title="Edit">
            <IconButton size="small" onClick={(e) => { e.stopPropagation(); onEdit(resource); }}>
              <StarBorderIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        ) : null}
        {onRemoveFromLibrary ? (
          <Tooltip title="Remove from folder">
            <IconButton
              size="small"
              onClick={(e) => {
                e.stopPropagation();
                onRemoveFromLibrary(resource);
              }}
            >
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        ) : null}
      </Box>
    </Box>
  );
}
