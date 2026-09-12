require('dotenv').config();
const express = require('express');
const fs = require('fs');
const path = require('path');

const app = express();
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

const PORT = process.env.PORT || 8080;
const SLACK_TOKEN = process.env.SLACK_BOT_TOKEN;
const SLACK_CHANNEL = process.env.SLACK_CHANNEL || '#tous-deadweight';
const FIXTURES_DIR = path.join(__dirname, '..', 'fixtures');

function loadJSON(filename) {
  const filePath = path.join(FIXTURES_DIR, filename);
  return JSON.parse(fs.readFileSync(filePath, 'utf-8'));
}

// ---- C2 : construction du message Block Kit ----
function buildReviewMessage(finding, proof) {
  const verdictEmoji = proof.verdict === 'pass' ? '✅' : '❌';
  const savingEur = finding.est_saving_month_eur?.toFixed(0) ?? '?';

  return {
    channel: SLACK_CHANNEL,
    text: `Revue Deadweight — ${finding.workflow_name}`,
    blocks: [
      {
        type: 'header',
        text: { type: 'plain_text', text: `🔍 ${finding.workflow_name}` },
      },
      {
        type: 'section',
        text: {
          type: 'mrkdwn',
          text: `*${finding.title}*\nNœud : \`${finding.node_name}\` — règle: \`${finding.rule}\` (sévérité: ${finding.severity})`,
        },
      },
      {
        type: 'section',
        fields: [
          { type: 'mrkdwn', text: `*Verdict:*\n${verdictEmoji} ${proof.verdict}` },
          { type: 'mrkdwn', text: `*Accord:*\n${(proof.agreement_rate * 100).toFixed(1)}%` },
          { type: 'mrkdwn', text: `*Coût:*\n${proof.cost_factor}x moins cher` },
          { type: 'mrkdwn', text: `*Latence p95:*\n${proof.p95_before_ms}ms → ${proof.p95_after_ms}ms` },
        ],
      },
      {
        type: 'section',
        text: {
          type: 'mrkdwn',
          text: `💰 Économie estimée : *${savingEur}€/mois*`,
        },
      },
      {
        type: 'actions',
        block_id: 'review_actions',
        elements: [
          {
            type: 'button',
            text: { type: 'plain_text', text: '✅ Appliquer' },
            action_id: 'apply_patch',
            value: finding.finding_id,
            style: 'primary',
          },
          {
            type: 'button',
            text: { type: 'plain_text', text: '❌ Ignorer' },
            action_id: 'ignore_patch',
            value: finding.finding_id,
          },
        ],
      },
    ],
  };
}

// ---- Route de test ----
app.get('/ping', async (req, res) => {
  try {
    const result = await fetch('https://slack.com/api/chat.postMessage', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${SLACK_TOKEN}`,
        'Content-Type': 'application/json; charset=utf-8',
      },
      body: JSON.stringify({ channel: SLACK_CHANNEL, text: 'pong from deadweight habitat 🏓' }),
    });
    const data = await result.json();
    res.json(data);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: err.message });
  }
});

// ---- C2 : poster le message de revue ----
app.get('/review/:findingId', async (req, res) => {
  try {
    const finding = loadJSON('finding.json');
    const proof = loadJSON('proof.json');

    if (finding.finding_id !== req.params.findingId) {
      return res.status(404).json({ error: 'finding not found (only f_001 fixture available for now)' });
    }

    const message = buildReviewMessage(finding, proof);

    const result = await fetch('https://slack.com/api/chat.postMessage', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${SLACK_TOKEN}`,
        'Content-Type': 'application/json; charset=utf-8',
      },
      body: JSON.stringify(message),
    });
    const data = await result.json();
    res.json(data);
  } catch (err) {
    console.error(err);
    res.status(500).json({ error: err.message });
  }
});

// ---- C3 : bouton "Appliquer" -> envoie le patch dans n8n ----
app.post('/slack/interactions', async (req, res) => {
  // Répond immédiatement à Slack pour éviter le timeout (3 secondes max)
  res.status(200).send('');

  try {
    const payload = JSON.parse(req.body.payload);
    const action = payload.actions[0];
    const responseUrl = payload.response_url;

    let replyMessage;

    if (action.action_id === 'apply_patch') {
      const patch = loadJSON('patch.json');
      const workflowToImport = {
        ...patch.patched_workflow,
        active: false,
      };

      const n8nUrl = process.env.N8N_URL;
      const n8nKey = process.env.N8N_API_KEY;

      if (!n8nUrl || !n8nKey) {
        console.warn('N8N_URL ou N8N_API_KEY manquant — simulation seulement');
        replyMessage = {
          response_type: 'in_channel',
          replace_original: false,
          text: '⚠️ N8N non configuré — patch simulé (voir logs serveur).',
        };
      } else {
        const importResult = await fetch(`${n8nUrl}/api/v1/workflows`, {
          method: 'POST',
          headers: {
            'X-N8N-API-KEY': n8nKey,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(workflowToImport),
        });
        const importData = await importResult.json();
        console.log('n8n import result:', importData);

        replyMessage = {
          response_type: 'in_channel',
          replace_original: false,
          text: `✅ Workflow patché créé dans n8n : *${workflowToImport.name}*`,
        };
      }
    } else if (action.action_id === 'ignore_patch') {
      replyMessage = {
        response_type: 'ephemeral',
        replace_original: false,
        text: '👍 Patch ignoré.',
      };
    } else {
      replyMessage = { text: 'Action non reconnue' };
    }

    // Envoi de la vraie réponse vers Slack via response_url
    await fetch(responseUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(replyMessage),
    });
  } catch (err) {
    console.error(err);
  }
});

app.listen(PORT, () => {
  console.log(`Habitat running on http://localhost:${PORT}`);
});