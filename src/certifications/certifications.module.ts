import { Module } from '@nestjs/common';
import { ProfileModule } from '../profile/profile.module.js';
import { CertificationsController } from './certifications.controller.js';
import { CertificationsService } from './certifications.service.js';

@Module({
  imports: [ProfileModule],
  controllers: [CertificationsController],
  providers: [CertificationsService],
})
export class CertificationsModule {}
