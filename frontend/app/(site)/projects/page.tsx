import type { Metadata } from 'next';

import { ProjectsDashboard } from '@/components/site/ProjectsDashboard';

export const metadata: Metadata = {
  title: 'My Analyses',
  description: 'Saved solar estimates, with their locations, sizes and expected generation.',
};

export default function ProjectsPage() {
  return <ProjectsDashboard />;
}
