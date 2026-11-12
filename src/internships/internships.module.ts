import { Module } from '@nestjs/common';
import { ProfileModule } from '../profile/profile.module.js';
import { InternshipsController } from './internships.controller.js';
import { InternshipsService } from './internships.service.js';

@Module({
  imports: [ProfileModule],
  controllers: [InternshipsController],
  providers: [InternshipsService],
})
export class InternshipsModule {}
