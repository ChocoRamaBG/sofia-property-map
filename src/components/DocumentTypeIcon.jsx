import React from 'react';
import { FileCheck2, HardHat, MapPin, PenTool } from 'lucide-react';

// One visual identity for each register throughout filters, results and details.
export const DOCUMENT_TYPE_ICONS = {
  building_permits: HardHat,
  projecting_visas: PenTool,
  exploitation_certificates: FileCheck2,
  exploitation_certificates_legacy: FileCheck2,
  no_records: MapPin,
};

export default function DocumentTypeIcon({ type, size = 18, ...props }) {
  const Icon = DOCUMENT_TYPE_ICONS[type] || MapPin;
  return <Icon size={size} strokeWidth={2} aria-hidden="true" {...props} />;
}
