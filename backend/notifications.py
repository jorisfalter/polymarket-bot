"""
Notification system for Polymarket Insider Detector
Supports: Postmark (email), Webhook (n8n/Zapier/Make)
"""
import httpx
from typing import Optional, List
from loguru import logger
from datetime import datetime

from .config import settings
from .models import SuspiciousTrade, AlertSeverity


class NotificationService:
    """
    Send alerts via email (Postmark) or webhook (n8n, etc.)
    """
    
    def __init__(self):
        self.postmark_token = settings.postmark_api_token
        self.postmark_from = settings.postmark_from_email
        self.alert_email = settings.alert_email
        self.webhook_url = settings.webhook_url
        self.min_severity = settings.notification_min_severity
        
    async def notify(self, suspicious: SuspiciousTrade) -> bool:
        """
        Send notification for a suspicious trade
        Returns True if at least one notification was sent
        """
        # Check severity threshold
        severity_levels = {
            AlertSeverity.LOW: 1,
            AlertSeverity.MEDIUM: 2,
            AlertSeverity.HIGH: 3,
            AlertSeverity.CRITICAL: 4
        }
        
        min_level = severity_levels.get(AlertSeverity(self.min_severity), 2)
        trade_level = severity_levels.get(suspicious.severity, 1)
        
        if trade_level < min_level:
            return False
        
        sent = False
        
        # Try Postmark email
        if self.postmark_token and self.alert_email:
            try:
                await self._send_postmark(suspicious)
                sent = True
                logger.info(f"📧 Email sent for {suspicious.severity.value} alert")
            except Exception as e:
                logger.error(f"Failed to send email: {e}")
        
        # Try webhook (n8n, Zapier, Make, etc.)
        if self.webhook_url:
            try:
                await self._send_webhook(suspicious)
                sent = True
                logger.info(f"🔗 Webhook sent for {suspicious.severity.value} alert")
            except Exception as e:
                logger.error(f"Failed to send webhook: {e}")
        
        return sent
    
    async def _send_postmark(self, suspicious: SuspiciousTrade):
        """Send email via Postmark"""
        trade = suspicious.trade
        wallet = suspicious.wallet
        
        # Build email content
        subject = f"🚨 [{suspicious.severity.value.upper()}] Polymarket Insider Alert"
        
        html_body = f"""
        <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: 0 auto; background: #1a1a2e; color: #eee; padding: 24px; border-radius: 12px;">
            <h1 style="color: #00ff88; margin: 0 0 8px 0; font-size: 18px;">🔍 Insider Alert Detected</h1>
            <p style="color: #888; margin: 0 0 24px 0; font-size: 14px;">{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}</p>
            
            <div style="background: #252540; padding: 16px; border-radius: 8px; margin-bottom: 16px; border-left: 4px solid {self._severity_color(suspicious.severity)};">
                <h2 style="margin: 0 0 8px 0; font-size: 16px; color: #fff;">{trade.market_question[:100]}</h2>
                <span style="background: {self._severity_color(suspicious.severity)}22; color: {self._severity_color(suspicious.severity)}; padding: 4px 12px; border-radius: 4px; font-size: 12px; font-weight: 600; text-transform: uppercase;">
                    {suspicious.severity.value} - Score: {suspicious.suspicion_score:.0f}
                </span>
            </div>
            
            <h3 style="color: #888; font-size: 12px; text-transform: uppercase; margin: 16px 0 8px 0;">🚩 Red Flags</h3>
            <ul style="margin: 0; padding-left: 20px; color: #00ff88;">
                {''.join(f'<li style="margin-bottom: 4px;">{flag}</li>' for flag in suspicious.flags)}
            </ul>
            
            <h3 style="color: #888; font-size: 12px; text-transform: uppercase; margin: 16px 0 8px 0;">💰 Trade Details</h3>
            <table style="width: 100%; font-size: 14px;">
                <tr><td style="color: #888; padding: 4px 0;">Side</td><td style="color: {'#00ff88' if trade.side == 'BUY' else '#ff3366'}; font-weight: 600;">{trade.side}</td></tr>
                <tr><td style="color: #888; padding: 4px 0;">Notional</td><td style="color: #00d4ff; font-weight: 600;">${trade.notional_usd:,.0f}</td></tr>
                <tr><td style="color: #888; padding: 4px 0;">Price</td><td>{trade.price:.1f}¢</td></tr>
                <tr><td style="color: #888; padding: 4px 0;">Shares</td><td>{trade.shares:,.0f}</td></tr>
                <tr><td style="color: #888; padding: 4px 0;">Potential Return</td><td style="color: #00ff88;">{suspicious.potential_return_pct:.0f}%</td></tr>
            </table>
            
            <h3 style="color: #888; font-size: 12px; text-transform: uppercase; margin: 16px 0 8px 0;">👛 Wallet Profile</h3>
            <table style="width: 100%; font-size: 14px;">
                <tr><td style="color: #888; padding: 4px 0;">Address</td><td style="font-family: monospace; font-size: 12px;"><a href="https://polymarket.com/@{wallet.address}" style="color: #00d4ff;">{wallet.address[:20]}...</a></td></tr>
                <tr><td style="color: #888; padding: 4px 0;">Total Trades</td><td style="color: {'#ff3366' if wallet.total_trades < 10 else '#eee'};">{wallet.total_trades}</td></tr>
                <tr><td style="color: #888; padding: 4px 0;">Unique Markets</td><td style="color: {'#ff3366' if wallet.unique_markets < 5 else '#eee'};">{wallet.unique_markets}</td></tr>
                <tr><td style="color: #888; padding: 4px 0;">Win Rate</td><td>{f'{wallet.win_rate*100:.0f}%' if wallet.win_rate else 'N/A'}</td></tr>
            </table>
            
            <div style="margin-top: 24px; padding-top: 16px; border-top: 1px solid #333; font-size: 12px; color: #666;">
                <a href="http://localhost:8000" style="color: #00d4ff;">Open Dashboard</a> • 
                <a href="https://polymarket.com/{trade.market_slug}" style="color: #00d4ff;">View Market</a>
            </div>
        </div>
        """
        
        text_body = f"""
🔍 POLYMARKET INSIDER ALERT
{'-' * 40}
Severity: {suspicious.severity.value.upper()} (Score: {suspicious.suspicion_score:.0f})
Market: {trade.market_question[:80]}

RED FLAGS:
{chr(10).join(f'• {flag}' for flag in suspicious.flags)}

TRADE:
• Side: {trade.side}
• Size: ${trade.notional_usd:,.0f}
• Price: {trade.price:.1f}¢
• Potential Return: {suspicious.potential_return_pct:.0f}%

WALLET:
• Address: {wallet.address[:20]}...
• Total Trades: {wallet.total_trades}
• Unique Markets: {wallet.unique_markets}

View: https://polymarket.com/{trade.market_slug}
        """
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://api.postmarkapp.com/email",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "X-Postmark-Server-Token": self.postmark_token
                },
                json={
                    "From": self.postmark_from,
                    "To": self.alert_email,
                    "Subject": subject,
                    "HtmlBody": html_body,
                    "TextBody": text_body,
                    "MessageStream": "outbound"
                }
            )
            response.raise_for_status()
    
    async def _send_webhook(self, suspicious: SuspiciousTrade):
        """Send to webhook (n8n, Zapier, Make, etc.)"""
        trade = suspicious.trade
        wallet = suspicious.wallet
        
        payload = {
            "event": "insider_alert",
            "timestamp": datetime.utcnow().isoformat(),
            "severity": suspicious.severity.value,
            "suspicion_score": suspicious.suspicion_score,
            "flags": suspicious.flags,
            "trade": {
                "market_question": trade.market_question,
                "market_slug": trade.market_slug,
                "market_url": f"https://polymarket.com/{trade.market_slug}",
                "side": trade.side,
                "notional_usd": trade.notional_usd,
                "price_cents": trade.price,
                "shares": trade.shares,
                "potential_return_pct": suspicious.potential_return_pct,
                "timestamp": trade.timestamp.isoformat()
            },
            "wallet": {
                "address": wallet.address,
                "polymarket_url": f"https://polymarket.com/@{wallet.address}",
                "total_trades": wallet.total_trades,
                "unique_markets": wallet.unique_markets,
                "win_rate": wallet.win_rate,
                "is_fresh_wallet": wallet.is_fresh_wallet,
                "is_whale": wallet.is_whale
            }
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.webhook_url,
                json=payload,
                timeout=10.0
            )
            response.raise_for_status()
    
    def _severity_color(self, severity: AlertSeverity) -> str:
        colors = {
            AlertSeverity.CRITICAL: "#ff3366",
            AlertSeverity.HIGH: "#ff6633",
            AlertSeverity.MEDIUM: "#ffaa00",
            AlertSeverity.LOW: "#00d4ff"
        }
        return colors.get(severity, "#888")


# Singleton instance
notifier: Optional[NotificationService] = None

def get_notifier() -> NotificationService:
    global notifier
    if notifier is None:
        notifier = NotificationService()
    return notifier

