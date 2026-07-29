const { publishToDevice } = require('./utils/mqttPublisher');

async function testSyncFlow() {
  console.log('--- Testing Setpoints Sync Request via Private Broker ---');
  try {
    await publishToDevice('inhydro/system2/room1/setpoints/request_sync', '1');
    console.log('✅ Successfully published request_sync=1 to inhydro/system2/room1/setpoints/request_sync');
  } catch (err) {
    console.error('❌ Failed to publish request_sync:', err.message);
  }

  console.log('--- Testing Setpoints Update Push via Private Broker ---');
  try {
    await publishToDevice('inhydro/system2/room1/setpoints/update', {
      "EC MIN": 1.2,
      "EC MAX": 2.5,
      "PH LOW": 5.8,
      "PH HIGH": 6.5,
      "pushedAt": new Date().toISOString()
    });
    console.log('✅ Successfully published setpoints update to inhydro/system2/room1/setpoints/update');
  } catch (err) {
    console.error('❌ Failed to publish setpoints update:', err.message);
  }
}

testSyncFlow();
