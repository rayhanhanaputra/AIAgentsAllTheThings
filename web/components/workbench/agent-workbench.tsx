'use client';

import { useEffect, useState } from 'react';
import Image from 'next/image';
import {
  Braces,
  ChevronRight,
  FolderOpen,
  History as HistoryIcon,
  Moon,
  FlaskConical,
  Server,
  Sun,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  checkHealth,
  listTargets,
  type TargetProfile,
} from '@/lib/workbench-api';
import { Intruder } from './intruder';
import { History } from './history';
import { Workbench } from './input-channels';
import { Targets } from './targets';

export function AgentWorkbench() {
  const [dark, setDark] = useState(false);
  const [connection, setConnection] = useState<
    'checking' | 'online' | 'offline'
  >('checking');
  const [targets, setTargets] = useState<TargetProfile[]>([]);

  async function refreshTargets() {
    setTargets((await listTargets()).targets);
  }

  useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
  }, [dark]);

  useEffect(() => {
    let active = true;
    async function refresh() {
      try {
        const health = await checkHealth();
        if (active)
          setConnection(health.status === 'ok' ? 'online' : 'offline');
      } catch {
        if (active) setConnection('offline');
      }
    }
    void refresh();
    void listTargets()
      .then((response) => {
        if (active) setTargets(response.targets);
      })
      .catch(() => undefined);
    const interval = window.setInterval(refresh, 30000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, []);

  return (
    <main className="workbench">
      <header className="app-header">
        <div className="brand">
          <div className="brand-mark">
            <Image
              src="/logo-aiagentsallthethings.png"
              alt=""
              width={32}
              height={32}
            />
          </div>
          <div className="brand-copy">
            <strong>AIAgentsAllTheThings</strong>
            <span>Agent Lab</span>
          </div>
          <div className="brand-divider" />
          <div className="workspace-label">
            <FolderOpen size={13} /> Workspace <ChevronRight size={11} />
            <span>Local project</span>
          </div>
        </div>
        <div className="header-actions">
          <Button
            className="wb-button wb-icon"
            variant="ghost"
            onClick={() => setDark(!dark)}
            aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'}
            title={dark ? 'Light theme' : 'Dark theme'}
          >
            {dark ? <Sun /> : <Moon />}
          </Button>
        </div>
      </header>

      <Tabs defaultValue="workbench" className="workbench-tabs">
        <div className="tool-navigation">
          <TabsList aria-label="Workbench tools">
            <TabsTrigger value="workbench">
              <FlaskConical />
              Workbench
            </TabsTrigger>
            <TabsTrigger value="campaigns">
              <Braces />
              Campaigns
            </TabsTrigger>
            <TabsTrigger value="targets">
              <Server />
              Targets
            </TabsTrigger>
            <TabsTrigger value="history">
              <HistoryIcon />
              History
            </TabsTrigger>
          </TabsList>
          <span className="tool-caption">Agent security workbench</span>
        </div>
        <TabsContent value="workbench" className="tool-content" keepMounted>
          <Workbench targets={targets} />
        </TabsContent>
        <TabsContent value="campaigns" className="tool-content" keepMounted>
          <Intruder targets={targets} />
        </TabsContent>
        <TabsContent value="targets" className="tool-content">
          <Targets targets={targets} onChanged={refreshTargets} />
        </TabsContent>
        <TabsContent value="history" className="tool-content">
          <History />
        </TabsContent>
      </Tabs>

      <footer className="status-bar">
        <div className="status-group">
          <span data-api-status={connection}>Local workspace</span>
        </div>
        <div className="status-group">
          <span>AIAgentsAllTheThings v0.1</span>
        </div>
      </footer>
    </main>
  );
}
