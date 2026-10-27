import React, { useEffect, useRef } from 'react';
import { ArrowLeft, MapPin, X } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import RegisteredBusinesses from './RegisteredBusinesses';
import './BusinessAddressDetails.css';

export default function BusinessAddressDetails({ address, onClose, onBackToSearch }) {
  const { pick } = useI18n();
  const heading = useRef(null);
  const identifier = address?.address_id;
  useEffect(() => { heading.current?.focus({ preventScroll: true }); }, [identifier]);
  if (!/^address-[a-f0-9]{24}$/.test(identifier || '')) return null;
  return <div className="details-panel business-address-details" onKeyDown={(event) => { if (event.key === 'Escape' && !event.defaultPrevented) { event.stopPropagation(); onClose?.(); } }}>
    {onBackToSearch && <button className="details-back-search" type="button" onClick={onBackToSearch}><ArrowLeft size={17} aria-hidden="true" /><span>{pick('Обратно към резултатите от търсенето', 'Back to search results')}</span></button>}
    <div className="details-header"><div><p className="eyebrow">{pick('Официален адрес', 'Official address')}</p><h2 ref={heading} tabIndex={-1}>{address.label || address.registered_address || pick('Фирмен адрес', 'Registered business address')}</h2><span className="details-coordinate-type"><MapPin size={12} aria-hidden="true" />{pick('Адресна точка · Столична община', 'Address point · Sofia Municipality')}</span></div>{onClose && <div className="details-header-actions"><button type="button" onClick={onClose} aria-label={pick('Затвори', 'Close')}><X size={19} aria-hidden="true" /></button></div>}</div>
    <div className="details-scroll"><p className="business-address-parcel-note">{pick('Тази точка обозначава официален адрес. За него не е установен еднозначен кадастрален парцел.', 'This point marks an official address. Its cadastral parcel has not been unambiguously established.')}</p><RegisteredBusinesses addressId={identifier} /></div>
  </div>;
}
