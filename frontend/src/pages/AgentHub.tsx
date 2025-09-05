// pages/AgentHub.tsx
// Copyright Thales 2025
//
// Licensed under the Apache License, Version 2.0 (the "License");
// ...

import {
  Box,
  Typography,
  useTheme,
  Button,
  Chip,
  Fade,
  Tabs,
  Tab,
  Card,
  CardContent,
  ListItemIcon,
} from "@mui/material";
import { useState, useEffect, SyntheticEvent, useMemo } from "react";
import { useTranslation } from "react-i18next";
import SearchIcon from "@mui/icons-material/Search";
import AddIcon from "@mui/icons-material/Add";
import FilterListIcon from "@mui/icons-material/FilterList";
import StarIcon from "@mui/icons-material/Star";
import LocalOfferIcon from "@mui/icons-material/LocalOffer";
import Grid2 from "@mui/material/Grid2";
import yaml from "js-yaml";

import { LoadingSpinner } from "../utils/loadingSpinner";
import { TopBar } from "../common/TopBar";
import { AgentCard } from "../components/agentHub/AgentCard";
import { CreateAgentModal } from "../components/agentHub/CreateAgentModal";
import { useConfirmationDialog } from "../components/ConfirmationDialogProvider";

// Agentic flows OpenAPI
import {
  AgenticFlow,
  GetAgenticFlowsAgenticV1ChatbotAgenticflowsGetApiResponse,
  useDeleteAgentAgenticV1AgentsNameDeleteMutation,
  useLazyGetAgenticFlowsAgenticV1ChatbotAgenticflowsGetQuery,
} from "../slices/agentic/agenticOpenApi";

// Knowledge Flow OpenAPI (Resources)
import {
  Resource as KFResource,
  // Adjust the hook name if your generator differs.
  useLazyListResourcesByKindKnowledgeFlowV1ResourcesGetQuery,
} from "../slices/knowledgeFlow/knowledgeFlowOpenApi";

/* ----------------------- Compact helpers ----------------------- */

interface AgentCategory {
  name: string;
  isTag?: boolean;
}

/** Compact, multi-doc tolerant header parser. */
function parseHeaderFromContent(text?: string): Record<string, any> {
  if (typeof text !== "string") return {};
  const s = text.trim();
  if (!s) return {};

  // Fast-path: front-matter block at start
  if (s.startsWith("---")) {
    const fm = s.slice(3).split(/\n---\s*\n/, 1)[0];
    if (fm) {
      try {
        const h = yaml.load(fm);
        if (h && typeof h === "object") return h as Record<string, any>;
      } catch {}
    }
  }

  // Load all YAML docs (works for single or multi-doc). Fallback to JSON.
  const docs: any[] = [];
  try {
    yaml.loadAll(s, (d) => d && typeof d === "object" && docs.push(d));
  } catch {
    if (s.startsWith("{")) {
      try {
        const j = JSON.parse(s);
        if (j && typeof j === "object") docs.push(j);
      } catch {}
    }
  }

  // Pick the most informative doc.
  const pick =
    docs.find((d) => d.kind) ||
    docs.find((d) => Array.isArray(d.servers) || Array.isArray(d.mcpServers) || Array.isArray(d.mcp_servers)) ||
    docs[0];

  return pick && typeof pick === "object" ? (pick as Record<string, any>) : {};
}

/** Map a resource (kind: agent) to the AgenticFlow shape. */
function mapResourceAgentToFlow(r: KFResource): AgenticFlow | null {
  const h = parseHeaderFromContent((r as any)?.content);
  const pick = <T,>(...v: (T | undefined | null)[]) => v.find((x) => x !== undefined && x !== null);

  const name = pick<string>((r as any)?.name, (r as any)?.metadata?.name, h?.name);
  if (!name) return null;

  const role = pick<string>((r as any)?.role, (r as any)?.metadata?.role, h?.role);
  const nickname = pick<string>((r as any)?.nickname, (r as any)?.metadata?.nickname, h?.nickname);
  const description = pick<string>((r as any)?.description, (r as any)?.metadata?.description, h?.description);
  const icon = pick<string>((r as any)?.icon, (r as any)?.metadata?.icon, h?.icon);
  const labels =
    (pick<string[]>((r as any)?.labels, (r as any)?.metadata?.labels, h?.labels) ?? []) as string[];

  const tag = Array.isArray(labels) && labels.length ? String(labels[0]) : undefined;

  return {
    name,
    role,
    nickname,
    description,
    icon,
    experts: [], // required by AgenticFlow
    tag,
    tags: tag, // legacy compat
  } as AgenticFlow;
}

/** Merge flows + resources, dedupe by name (flows take precedence). */
function mergeAgents(flowAgents: AgenticFlow[], resourceAgents: AgenticFlow[]): AgenticFlow[] {
  const all = [...(resourceAgents || []), ...(flowAgents || [])].filter(
    (a): a is AgenticFlow => !!a && !!a.name
  );
  return [...new Map(all.map((a) => [a.name, a] as const)).values()];
}

const extractUniqueTags = (agents: AgenticFlow[]): string[] =>
  agents
    .map((a) => a.tag || "")
    .filter((t) => t && t.trim() !== "")
    .filter((tag, idx, self) => self.indexOf(tag) === idx);

const mapFlowsToAgents = (
  flows: GetAgenticFlowsAgenticV1ChatbotAgenticflowsGetApiResponse
): AgenticFlow[] =>
  (flows || []).map((f) => ({
    name: f.name,
    role: f.role,
    nickname: f.nickname ?? undefined,
    description: f.description,
    icon: f.icon ?? undefined,
    // ensure required property is present
    experts: Array.isArray((f as any).experts) ? (f as any).experts : [],
    tag: (f as any).tag ?? undefined,
    // legacy compatibility
    tags: (f as any).tag ?? undefined,
  })) as AgenticFlow[];

/* ----------------------- UI ----------------------- */

const ActionButton = ({
  icon,
  children,
  ...props
}: {
  icon: React.ReactNode;
  children: React.ReactNode;
} & React.ComponentProps<typeof Button>) => {
  const theme = useTheme();
  return (
    <Button
      startIcon={<ListItemIcon sx={{ minWidth: 0, mr: 0.75, color: "inherit" }}>{icon}</ListItemIcon>}
      size="small"
      {...props}
      sx={{
        borderRadius: 1.5,
        textTransform: "none",
        px: 1.25,
        height: 32,
        border: `1px solid ${theme.palette.divider}`,
        bgcolor: "transparent",
        color: "text.primary",
        "&:hover": {
          borderColor: theme.palette.primary.main,
          backgroundColor:
            theme.palette.mode === "dark" ? "rgba(25,118,210,0.10)" : "rgba(25,118,210,0.06)",
        },
        ...props.sx,
      }}
    >
      {children}
    </Button>
  );
};

export const AgentHub = () => {
  const theme = useTheme();
  const { t } = useTranslation();

  // Unified agents list (flows + resources)
  const [agents, setAgents] = useState<AgenticFlow[]>([]);
  const [tabValue, setTabValue] = useState(0);
  const [showElements, setShowElements] = useState(false);
  const [favoriteAgents, setFavoriteAgents] = useState<string[]>([]);
  const [categories, setCategories] = useState<AgentCategory[]>([{ name: "all" }, { name: "favorites" }]);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);

  const handleOpenCreateAgent = () => setIsCreateModalOpen(true);
  const handleCloseCreateAgent = () => setIsCreateModalOpen(false);

  // Agentic flows
  const [triggerGetFlows, { isFetching: loadingFlows }] =
    useLazyGetAgenticFlowsAgenticV1ChatbotAgenticflowsGetQuery();

  // Knowledge hub resources (kind=agent)
  const [triggerListAgentResources, { isFetching: loadingResources }] =
    useLazyListResourcesByKindKnowledgeFlowV1ResourcesGetQuery();

  const [deleteAgent] = useDeleteAgentAgenticV1AgentsNameDeleteMutation();
  const { showConfirmationDialog } = useConfirmationDialog();

  const handleDeleteAgent = (name: string) => {
    showConfirmationDialog({
      title: t("agentHub.confirmDeleteTitle"),
      message: t("agentHub.confirmDeleteMessage"),
      onConfirm: async () => {
        try {
          await deleteAgent({ name }).unwrap();
          fetchAgents();
        } catch (err) {
          console.error("Failed to delete agent:", err);
        }
      },
    });
  };

  /** Fetch both sources, merge and compute categories. */
  const fetchAgents = async () => {
    try {
      // 1) Agentic flows
      const flows = await triggerGetFlows().unwrap();
      const flowAgents = mapFlowsToAgents(flows);

      // 2) Resources with kind=agent
      let resourceAgents: AgenticFlow[] = [];
      try {
        const res = await triggerListAgentResources({ kind: "agent" }).unwrap();
        resourceAgents = (res as KFResource[])
          .map(mapResourceAgentToFlow)
          .filter(Boolean) as AgenticFlow[];
      } catch (e) {
        console.warn("[AgentHub] listing resources kind=agent failed:", e);
      }

      // 3) Merge (flows take precedence by name)
      const merged = mergeAgents(flowAgents, resourceAgents);
      setAgents(merged);

      // 4) Tabs/categories from unique tags
      const tags = extractUniqueTags(merged);
      setCategories([{ name: "all" }, { name: "favorites" }, ...tags.map((tag) => ({ name: tag, isTag: true }))]);

      // 5) Restore favorites
      const savedFavorites = localStorage.getItem("favoriteAgents");
      if (savedFavorites) setFavoriteAgents(JSON.parse(savedFavorites));
    } catch (err) {
      console.error("Error fetching agents:", err);
    }
  };

  useEffect(() => {
    setShowElements(true);
    fetchAgents();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleTabChange = (_event: SyntheticEvent, newValue: number) => setTabValue(newValue);

  const filteredAgents = useMemo(() => {
    if (tabValue === 0) return agents;
    if (tabValue === 1) return agents.filter((a) => favoriteAgents.includes(a.name));
    if (categories.length > 2 && tabValue >= 2) {
      const tagName = categories[tabValue].name;
      return agents.filter((a) => a.tag === tagName);
    }
    return agents;
  }, [tabValue, agents, favoriteAgents, categories]);

  const toggleFavorite = (agentName: string) => {
    const updated = favoriteAgents.includes(agentName)
      ? favoriteAgents.filter((n) => n !== agentName)
      : [...favoriteAgents, agentName];
    setFavoriteAgents(updated);
    localStorage.setItem("favoriteAgents", JSON.stringify(updated));
  };

  const sectionTitle = useMemo(() => {
    if (tabValue === 0) return t("agentHub.allAgents");
    if (tabValue === 1) return t("agentHub.favoriteAgents");
    if (categories.length > 2 && tabValue >= 2) return `${categories[tabValue].name} ${t("agentHub.agents")}`;
    return t("agentHub.agents");
  }, [tabValue, categories, t]);

  const isFetching = loadingFlows || loadingResources;

  return (
    <>
      <TopBar title={t("agentHub.title")} description={t("agentHub.description")} />

      <Box
        sx={{
          width: "100%",
          maxWidth: 1280,
          mx: "auto",
          px: { xs: 2, md: 3 },
          pt: { xs: 3, md: 4 },
          pb: { xs: 4, md: 6 },
        }}
      >
        {/* Header / Tabs */}
        <Fade in={showElements} timeout={900}>
          <Card
            variant="outlined"
            sx={{
              borderRadius: 2,
              bgcolor: "transparent",
              boxShadow: "none",
              borderColor: "divider",
              mb: 2,
            }}
          >
            <CardContent sx={{ py: 1, px: { xs: 1, md: 2 } }}>
              <Tabs
                value={tabValue}
                onChange={handleTabChange}
                variant="scrollable"
                scrollButtons="auto"
                sx={{
                  minHeight: 44,
                  "& .MuiTab-root": {
                    textTransform: "none",
                    fontSize: "0.9rem",
                    minHeight: 44,
                    minWidth: 120,
                    color: "text.secondary",
                  },
                  "& .Mui-selected": { color: "text.primary", fontWeight: 600 },
                  "& .MuiTabs-indicator": {
                    backgroundColor: theme.palette.primary.main,
                    height: 3,
                    borderRadius: 1.5,
                  },
                }}
              >
                {categories.map((category, index) => {
                  const isFav = category.name === "favorites";
                  const isTag = !!category.isTag;
                  const count =
                    isFav
                      ? favoriteAgents.length
                      : isTag
                      ? agents.filter((a) => a.tag === category.name).length
                      : agents.length;

                  return (
                    <Tab
                      key={`${category.name}-${index}`}
                      label={
                        <Box sx={{ display: "flex", alignItems: "center" }}>
                          {isFav && <StarIcon fontSize="small" sx={{ mr: 0.5, color: "warning.main" }} />}
                          {isTag && <LocalOfferIcon fontSize="small" sx={{ mr: 0.5, color: "text.secondary" }} />}
                          <Typography variant="body2" sx={{ textTransform: "capitalize" }}>
                            {t(`agentHub.categories.${category.name}`, category.name)}
                          </Typography>
                          <Chip
                            size="small"
                            label={count}
                            sx={{
                              ml: 1,
                              height: 18,
                              fontSize: "0.7rem",
                              bgcolor: "transparent",
                              border: `1px solid ${theme.palette.divider}`,
                              color: "text.secondary",
                            }}
                          />
                        </Box>
                      }
                    />
                  );
                })}
              </Tabs>
            </CardContent>
          </Card>
        </Fade>

        {/* Content */}
        <Fade in={showElements} timeout={1100}>
          <Card
            variant="outlined"
            sx={{
              borderRadius: 2,
              bgcolor: "transparent",
              boxShadow: "none",
              borderColor: "divider",
            }}
          >
            <CardContent sx={{ p: { xs: 2, md: 3 } }}>
              {isFetching ? (
                <Box display="flex" justifyContent="center" alignItems="center" minHeight="360px">
                  <LoadingSpinner />
                </Box>
              ) : (
                <>
                  {/* Section header */}
                  <Box display="flex" justifyContent="space-between" alignItems="center" mb={2}>
                    <Box display="flex" alignItems="center" gap={1}>
                      {tabValue === 1 && <StarIcon fontSize="small" sx={{ color: "warning.main" }} />}
                      {tabValue >= 2 && categories[tabValue]?.isTag && (
                        <LocalOfferIcon fontSize="small" sx={{ color: "text.secondary" }} />
                      )}
                      <Typography variant="h6" fontWeight={600}>
                        {sectionTitle}{" "}
                        <Typography component="span" variant="body2" color="text.secondary">
                          ({filteredAgents.length})
                        </Typography>
                      </Typography>
                    </Box>

                    <Box sx={{ display: "flex", gap: 1 }}>
                      <ActionButton icon={<SearchIcon />}>{t("agentHub.search")}</ActionButton>
                      <ActionButton icon={<FilterListIcon />}>{t("agentHub.filter")}</ActionButton>
                      <ActionButton icon={<AddIcon />} onClick={handleOpenCreateAgent}>
                        {t("agentHub.create")}
                      </ActionButton>
                    </Box>
                  </Box>

                  {/* Grid with uniform card heights */}
                  {filteredAgents.length > 0 ? (
                    <Grid2
                      container
                      spacing={2}
                      sx={{ alignItems: "stretch" }} // ensure children stretch to same row height
                    >
                      {filteredAgents.map((agent) => (
                        <Grid2
                          key={agent.name}
                          size={{ xs: 12, sm: 6, md: 4, lg: 4, xl: 4 }}
                          sx={{ display: "flex" }}
                        >
                          <Fade in timeout={500}>
                            {/* Wrapper enforces a minimum card height and lets AgentCard fill it */}
                            <Box
                              sx={{
                                width: "100%",

                              }}
                            >
                              <AgentCard
                                agent={agent}
                                onDelete={handleDeleteAgent}
                                isFavorite={favoriteAgents.includes(agent.name)}
                                onToggleFavorite={toggleFavorite}
                                allAgents={agents}
                              />
                            </Box>
                          </Fade>
                        </Grid2>
                      ))}
                    </Grid2>
                  ) : (
                    <Box
                      display="flex"
                      flexDirection="column"
                      alignItems="center"
                      justifyContent="center"
                      minHeight="280px"
                      sx={{
                        border: `1px dashed ${theme.palette.divider}`,
                        borderRadius: 2,
                        p: 3,
                      }}
                    >
                      <Typography variant="subtitle1" color="text.secondary" align="center">
                        {t("agentHub.noAgents")}
                      </Typography>
                      {tabValue === 1 && (
                        <Typography variant="body2" color="text.secondary" align="center" sx={{ mt: 0.5 }}>
                          {t("agentHub.noFavorites")}
                        </Typography>
                      )}
                      {tabValue >= 2 && (
                        <Typography variant="body2" color="text.secondary" align="center" sx={{ mt: 0.5 }}>
                          {t("agentHub.noTag", { tag: categories[tabValue]?.name })}
                        </Typography>
                      )}
                    </Box>
                  )}

                  {/* Create modal */}
                  {isCreateModalOpen && (
                    <CreateAgentModal
                      open={isCreateModalOpen}
                      onClose={handleCloseCreateAgent}
                      onCreated={() => {
                        handleCloseCreateAgent();
                        fetchAgents();
                      }}
                    />
                  )}
                </>
              )}
            </CardContent>
          </Card>
        </Fade>
      </Box>
    </>
  );
};
